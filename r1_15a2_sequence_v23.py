"""V2.3: true contiguous saved-route branch proposals, with all-path impact audit.

All routes are read from an official Visum saved-path export.  No shortest path
construction or OD manipulation occurs here.  SQLite stores full route evidence
on disk rather than retaining the entire all-DSeg route set in Python memory.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
import json
import math
import sqlite3
import hashlib

import r1_15a2_core as core
from r1_15a2_supply import (ActualRouteCollector, SupplyContractError,
    SupplyPolicy, canonical_hash, check_addval_change, edge_key, integer,
    key_text, number)


def path_nodes(edges):
    if not edges:
        return ()
    if any(left[2] != right[1] for left, right in zip(edges, edges[1:])):
        raise SupplyContractError('DISCONNECTED_PATH_SEQUENCE')
    return (edges[0][1],) + tuple(e[2] for e in edges)


def branch_pair(links_on, links_off, profile):
    """Return actual ON/OFF diverge/rejoin branches around a counted ON link.

    The end nodes of each extracted branch must be the same, and the profile
    link must be inside the selected ON branch.  No edge is invented.
    """
    on = tuple(links_on); off = tuple(links_off)
    if profile not in on or profile in off or not off:
        return None
    nodes_on, nodes_off = path_nodes(on), path_nodes(off)
    if not nodes_on or not nodes_off:
        return None
    off_at = defaultdict(list)
    for pos, node in enumerate(nodes_off):
        off_at[node].append(pos)
    best = None
    for p in (idx for idx, edge in enumerate(on) if edge == profile):
        # Exact common-node anchors: closest valid divergence/rejoin around p.
        # Bisect avoids materializing the Cartesian product of all anchor pairs.
        for lo in range(p, -1, -1):
            for fo in off_at.get(nodes_on[lo], ()):
                for hi in range(p+1, len(nodes_on)):
                    possible=off_at.get(nodes_on[hi], ())
                    j=bisect_right(possible,fo)
                    if j>=len(possible):continue
                    fh=possible[j]
                    if lo>=hi or fo>=fh:continue
                    seq_on=on[lo:hi]; seq_off=off[fo:fh]
                    if not seq_on or not seq_off or seq_on==seq_off or profile not in seq_on:
                        continue
                    if seq_on[0][1]!=seq_off[0][1] or seq_on[-1][2]!=seq_off[-1][2]:
                        continue
                    score=(len(seq_on)+len(seq_off),len(seq_on),lo,fo,hi,fh)
                    if best is None or score<best[0]:
                        best=(score,seq_on,seq_off,(nodes_on[lo],nodes_on[hi]))
        if best is not None:
            break
    if best is None:
        return None
    _, on_seg, off_seg, anchors = best
    return {'on': on_seg, 'off': off_seg, 'anchors': anchors}


def actual_on_probe_window(seq, profile, limit=3):
    """A witnessed contiguous route window; not a synthetic alternative."""
    seq=tuple(seq)
    if profile not in seq:
        raise SupplyContractError('PROBE_PROFILE_NOT_ON_ACTUAL_ROUTE')
    width=min(len(seq),integer(limit))
    if width<1:
        raise SupplyContractError('EMPTY_PROBE_ROUTE')
    pos=seq.index(profile)
    start=max(0,min(pos-width//2,len(seq)-width))
    return seq[start:start+width]


@dataclass
class SequenceEvidence:
    seq: tuple
    anchor: tuple
    support: float = 0.
    pairs: int = 0
    markets: int = 0
    on_volume: float = 0.
    off_volume: float = 0.
    probe: bool = False
    example: tuple = ()
    shared_edges: set = field(default_factory=set)


class ActualSequenceRouteCollector(ActualRouteCollector):
    """Augments the V2.2 verified collector with exact-sequence and route-store evidence."""
    def __init__(self, profiles, policy, parent_hash, editable_keys,
                 db_path=':memory:', max_unique_sequences=100000,
                 max_pairs_per_market=64, duplicate_scope_policy="FAIL"):
        super().__init__(profiles, policy, parent_hash, editable_keys,
                         duplicate_scope_policy=duplicate_scope_policy)
        self.route_db_path = str(db_path)
        if db_path != ':memory:':
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            if Path(db_path).exists():
                raise SupplyContractError('ROUTE_STORE_WOULD_REPLACE_EXISTING_EVIDENCE')
        self.db = sqlite3.connect(self.route_db_path)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('''CREATE TABLE routes (
           route_id INTEGER PRIMARY KEY, dseg TEXT NOT NULL, orig INTEGER NOT NULL,
           dest INTEGER NOT NULL, path_index INTEGER NOT NULL, volume REAL NOT NULL,
           sequence_json TEXT NOT NULL, cal_profile_ids TEXT NOT NULL,
           UNIQUE(dseg,orig,dest,path_index))''')
        self.db.execute('''CREATE TABLE route_edges (
           link_no INTEGER, from_no INTEGER, to_no INTEGER,
           route_id INTEGER, multiplicity INTEGER,
           UNIQUE(link_no,from_no,to_no,route_id))''')
        self.evidence = defaultdict(dict)
        self.route_count = 0
        self._indexed = False
        self.max_unique_sequences = integer(max_unique_sequences)
        self.max_pairs_per_market = integer(max_pairs_per_market)
        if self.max_unique_sequences < 1 or self.max_pairs_per_market < 1:
            raise SupplyContractError('INVALID_SEQUENCE_MEMORY_BUDGET')
        self.skipped_branches = Counter()
        self.protected = {i for i, row in enumerate(self.profiles) if
                          str(row.get('role', '')).upper() == 'CALIBRATION'
                          and number(row['observed']) > 0
                          and core.geh(number(row['model']), number(row['observed'])) < 5.}
        self.cal_indices = {i for i,row in enumerate(self.profiles) if
                            str(row.get('role','')).upper() == 'CALIBRATION'}

    def close(self):
        self.db.close()

    def _track(self, index, family, segment, anchors, support, on_v, off_v, market, pair, probe=False, opposing=()):
        # The key is an ACTUAL contiguous path segment, never an unordered edge set.
        segment = tuple(segment)
        if not segment or path_nodes(segment)[0] != anchors[0] or path_nodes(segment)[-1] != anchors[-1]:
            raise SupplyContractError('INVALID_CONTIGUOUS_SEGMENT_PROOF')
        key = (family, segment)
        obj = self.evidence[index].get(key)
        if obj is None:
            if sum(map(len, self.evidence.values())) >= self.max_unique_sequences:
                raise SupplyContractError('UNBOUNDED_SEQUENCE_AUTHORITY_SIZE')
            obj = SequenceEvidence(segment, tuple(anchors), probe=bool(probe), example=tuple(pair))
            self.evidence[index][key] = obj
        obj.shared_edges.update(set(segment).intersection(opposing))
        obj.support += support
        obj.pairs += 1
        obj.on_volume += on_v
        obj.off_volume += off_v
        # Number of distinct market contributions (not a route-count proxy).
        if getattr(obj, '_last_market', None) != market:
            obj.markets += 1
            obj._last_market = market
        obj.probe = bool(obj.probe or probe)

    def _add_pair_evidence(self, market, routes):
        for i in self.drivers:
            group = self.key_groups[i]
            on = [r for r in routes if any(k in r['multiplicity'] for k in group)]
            if not on:
                continue
            off = [r for r in routes if not any(k in r['multiplicity'] for k in group)]
            on.sort(key=lambda r:(-r['volume'],r['pk']))
            off.sort(key=lambda r:(-r['volume'],r['pk']))
            if not off:
                # A labeled probe; lack of a saved alternative is NOT evidence of no alternative.
                for o in on:
                    profile = next(k for k in group if k in o['multiplicity'])
                    seq = actual_on_probe_window(o['seq'],profile)
                    self._track(i, 'ON_ONLY_PROBE', seq, (seq[0][1],seq[-1][2]),
                                o['volume'],o['volume'],0.,market,(o['pk'],),True)
                continue
            pairs = [(o,f) for o in on for f in off]
            pairs.sort(key=lambda pair: (-pair[0]['volume']*pair[1]['volume'],pair[0]['pk'],pair[1]['pk']))
            if len(pairs) > self.max_pairs_per_market:
                self.skipped_branches['PAIRS_TRUNCATED_REQUIRE_AUTHORITY_REVIEW'] += len(pairs)-self.max_pairs_per_market
                # Do not infer the omitted path-pair patterns as evidence for a candidate.
            matched=False
            for o,f in pairs[:self.max_pairs_per_market]:
                profile = next(k for k in group if k in o['multiplicity'])
                split = branch_pair(o['seq'],f['seq'],profile)
                if split is None:
                    self.skipped_branches['NO_COMMON_DIVERGE_REJOIN_ANCHORS'] += 1
                    continue
                matched=True
                v_on = o['volume']; v_off = f['volume']
                on_market_volume = sum(r['volume'] for r in on)
                off_market_volume = sum(r['volume'] for r in off)
                # Each on path volume is shared among competing off witnesses and vice versa.
                on_weight = v_on*v_off/max(off_market_volume,1e-30)
                off_weight = v_off*v_on/max(on_market_volume,1e-30)
                example=(o['pk'],f['pk'])
                self._track(i,'ON',split['on'],split['anchors'],on_weight,v_on,v_off,market,example,opposing=split['off'])
                self._track(i,'OFF',split['off'],split['anchors'],off_weight,v_on,v_off,market,example,opposing=split['on'])
            if not matched:
                # Different connector/end-node choices can eliminate common anchors.
                # Propose only the OBSERVED ON link, with explicit lower confidence.
                for o in on:
                    profile = next(k for k in group if k in o['multiplicity'])
                    seq=actual_on_probe_window(o['seq'],profile)
                    self._track(i,'ON_ONLY_PROBE',seq,(seq[0][1],seq[-1][2]),o['volume'],
                                o['volume'],0.,market,(o['pk'],),True)
                self.skipped_branches['NO_BRANCHED_PAIR_ON_ONLY_PROBE'] += 1

    def consume_stream(self, path_rows, pathlink_rows, dseg):
        """Join bounded official path-link records with routes using bounded memory.

        This is the read-only 15P design branch only.  Same original exact
        link/flow/branch authorities, but one OD market and one route at a time;
        no materialized entire-DSeg link array.  Any orphan, out-of-order route,
        invalid link sequence or missing interzonal evidence fails closed.
        """
        code = core.norm_code(dseg['code'])
        if any(batch['dseg'] == code for batch in self.batches):
            raise SupplyContractError('DUPLICATE_DSEG_BATCH')
        def route_pk(row, index_name):
            d = core.norm_code(row.get('dseg_code', code))
            p = (d, integer(row['OrigZoneNo']), integer(row['DestZoneNo']), integer(row[index_name]))
            if d != code or min(p[1:]) < 1:
                raise SupplyContractError('INVALID_SAVED_PATH_KEY')
            return p
        ordered = sorted(path_rows, key=lambda row: route_pk(row, 'Index'))
        links = iter(pathlink_rows)
        next_link = next(links, None)
        previous_pk = None
        previous_market = None
        market_routes = []
        positive = covered = 0
        total_volume = covered_volume = 0.0
        digest = hashlib.sha256()
        inserted = 0
        def finalize_market(market, routes):
            if market is None or not routes:
                return
            # The V2.2 source collector's flow-contrast algebra, unchanged.
            for i in self.drivers:
                group = self.key_groups[i]
                on = [r for r in routes if any(k in r['multiplicity'] for k in group)]
                if not on:
                    continue
                off = [r for r in routes if not any(k in r['multiplicity'] for k in group)]
                on_volume = sum(r['volume'] for r in on)
                off_volume = sum(r['volume'] for r in off)
                self.support[i] += sum(r['volume']*sum(r['multiplicity'].get(k, 0) for k in group)
                                       for r in on)
                self.market_counts[i] += 1
                if not off:
                    self.probe_only_counts[i] += 1
                on_edges = defaultdict(float)
                off_edges = defaultdict(float)
                for r in on:
                    for edge, n in r['multiplicity'].items():
                        if edge in self.editable:
                            on_edges[edge] += r['volume'] * n
                for r in off:
                    for edge, n in r['multiplicity'].items():
                        if edge in self.editable:
                            off_edges[edge] += r['volume'] * n
                for edge in set(on_edges) | set(off_edges):
                    contrast = on_edges[edge] / on_volume
                    if off_volume:
                        contrast -= off_edges[edge] / off_volume
                    self.edge_contrast[i][edge] += on_volume*contrast
            self._add_pair_evidence(market, routes)
        try:
            for row in ordered:
                pk = route_pk(row, 'Index')
                if pk == previous_pk:
                    raise SupplyContractError('DUPLICATE_SAVED_PATH')
                previous_pk = pk
                market = pk[:3]
                if market != previous_market:
                    finalize_market(previous_market, market_routes)
                    market_routes = []
                    previous_market = market
                vol = number(row['Vol(AP)'], 'path volume')
                if vol < 0:
                    raise SupplyContractError('NEGATIVE_SAVED_PATH_VOLUME')
                edges = []
                last_end = None
                while next_link is not None:
                    lpk = route_pk(next_link, 'PathIndex')
                    if lpk < pk:
                        raise SupplyContractError('ORPHAN_OR_OUT_OF_ORDER_SAVED_PATH_LINK')
                    if lpk > pk:
                        break
                    index = integer(next_link['Index'])
                    if index != len(edges) + 1:
                        raise SupplyContractError('SAVED_PATH_LINK_INDEX_NOT_CONTIGUOUS')
                    edge = edge_key(next_link)
                    if last_end is not None and edge[1] != last_end:
                        raise SupplyContractError('DISCONNECTED_OFFICIAL_PATH_LINK_SEQUENCE')
                    last_end = edge[2]
                    edges.append(edge)
                    next_link = next(links, None)
                if vol <= 0:
                    continue
                positive += 1
                total_volume += vol
                seq = tuple(edges)
                if not seq and pk[1] != pk[2]:
                    raise SupplyContractError('MISSING_POSITIVE_INTERZONAL_PATH_LINKS')
                covered += 1
                covered_volume += vol
                digest.update(json.dumps([pk, vol, seq], separators=(',', ':')).encode())
                multiplicity = Counter(seq)
                for edge, n in multiplicity.items():
                    self.edge_max_multiplicity[edge] = max(self.edge_max_multiplicity[edge], n)
                    for i in self.profile_index_by_key.get(edge, ()):
                        self.flow[i] += vol * n
                rec = dict(pk=pk, volume=vol, seq=seq, multiplicity=multiplicity)
                market_routes.append(rec)
                cal_ids = sorted({i for edge in multiplicity
                                  for i in self.profile_index_by_key.get(edge, ())
                                  if i in self.cal_indices})
                self.db.execute("INSERT INTO routes(dseg,orig,dest,path_index,volume,sequence_json,cal_profile_ids) VALUES(?,?,?,?,?,?,?)",(*pk,vol,json.dumps(seq,separators=(',',':')),json.dumps(cal_ids)))
                row_id = self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
                self.db.executemany("INSERT INTO route_edges (link_no,from_no,to_no,route_id,multiplicity) VALUES(?,?,?,?,?)",
                    [(*edge, row_id, n) for edge, n in multiplicity.items()])
                self.route_count += 1
                inserted += 1
                if inserted % 2000 == 0:
                    self.db.commit()
            if next_link is not None:
                raise SupplyContractError('ORPHAN_SAVED_PATH_LINK_AFTER_LAST_ROUTE')
            finalize_market(previous_market, market_routes)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        stats = {'dseg': code, 'positive_paths': positive, 'covered_paths': covered,
                 'path_coverage': covered / max(1, positive),
                 'volume_coverage': covered_volume / max(1e-30, total_volume),
                 'total_volume': total_volume, 'covered_volume': covered_volume,
                 'official_route_batch_hash': digest.hexdigest(),
                 'streaming': True, 'route_store_inserted': inserted}
        self.batches.append(stats)
        if (stats['path_coverage'] < self.policy.min_path_coverage or
            stats['volume_coverage'] < self.policy.min_path_volume_coverage):
            raise SupplyContractError('INSUFFICIENT_OFFICIAL_PATH_COVERAGE')
        return stats

    def consume(self, path_rows, pathlink_rows, dseg):
        # Reuse all validated V2.2 parity, directional-key, sequence-connectivity gates.
        batch = super().consume(path_rows,pathlink_rows,dseg)
        code = core.norm_code(dseg['code'])
        assembled = {}
        for row in path_rows:
            pk=(core.norm_code(row.get('dseg_code',code)),integer(row.get('OrigZoneNo')),
                integer(row.get('DestZoneNo')),integer(row.get('Index')))
            assembled[pk] = {'pk':pk,'volume':number(row['Vol(AP)']),'indexed':{}}
        for row in pathlink_rows:
            pk=(core.norm_code(row.get('dseg_code',code)),integer(row.get('OrigZoneNo')),
                integer(row.get('DestZoneNo')),integer(row.get('PathIndex')))
            assembled[pk]['indexed'][integer(row['Index'])]=edge_key(row)
        markets=defaultdict(list)
        with self.db:
            for pk, rec in sorted(assembled.items()):
                vol=rec['volume']
                if vol <= 0:
                    continue
                seq=tuple(v for _,v in sorted(rec['indexed'].items()))
                if not seq and pk[1] != pk[2]:
                    continue  # V2.2 coverage gate already decides whether the batch is complete.
                multiplicity=Counter(seq)
                cal_ids=sorted({i for edge in multiplicity for i in self.profile_index_by_key.get(edge,())
                                if i in self.cal_indices})
                self.db.execute('''INSERT INTO routes(dseg,orig,dest,path_index,volume,sequence_json,cal_profile_ids)
                    VALUES(?,?,?,?,?,?,?)''',(*pk,vol,json.dumps(seq,separators=(',',':')),json.dumps(cal_ids)))
                row_id=self.db.execute('SELECT last_insert_rowid()').fetchone()[0]
                self.db.executemany('''INSERT INTO route_edges
                    (link_no,from_no,to_no,route_id,multiplicity) VALUES(?,?,?,?,?)''',
                    [(*edge,row_id,n) for edge,n in multiplicity.items()])
                self.route_count += 1
                markets[pk[:3]].append(dict(pk=pk,seq=seq,multiplicity=multiplicity,volume=vol))
        for market, routes in markets.items():
            self._add_pair_evidence(market,routes)
        return batch

    def finish(self):
        proof=super().finish()
        if not self._indexed:
            self.db.execute('CREATE INDEX route_edges_lookup ON route_edges(link_no,from_no,to_no)')
            self.db.execute('CREATE INDEX route_edges_path ON route_edges(route_id)')
            self.db.commit()
            self._indexed=True
        proof['path_store_route_count']=self.route_count
        proof['path_store_type']='SQLITE_ON_DISK_IF_CONFIGURED'
        proof['unique_sequence_bundles']=sum(len(x) for x in self.evidence.values())
        proof['skipped_branch_cases']=dict(self.skipped_branches)
        return proof

    def impact(self, changes, driver_idx, driver_support):
        """EXACT current-path exposure (NOT a counterfactual equilibrium forecast)."""
        if not self._indexed:
            self.finish()
        if not changes:
            raise SupplyContractError('EMPTY_SEQUENCE_IMPACT')
        impact_by_path=defaultdict(float)
        for change in changes:
            key=tuple(change['key'])
            delta=10*number(change['delta'])
            for route_id,n in self.db.execute('''SELECT route_id,multiplicity FROM route_edges
                WHERE link_no=? AND from_no=? AND to_no=?''',key):
                impact_by_path[route_id] += delta*n
        protected_any={'routes':0,'volume':0.,'volume_weighted_abs_seconds':0.}
        groups=defaultdict(lambda:{'routes':0,'volume':0.,'volume_weighted_abs_seconds':0.,
                                    'volume_weighted_signed_seconds':0.})
        max_abs=0.; changed_count=0
        ids=sorted(k for k,v in impact_by_path.items() if abs(v)>1e-12)
        for offset in range(0,len(ids),800):
            batch=ids[offset:offset+800]
            params=','.join('?' for _ in batch)
            query='SELECT route_id,volume,cal_profile_ids FROM routes WHERE route_id IN ('+params+')'
            for rid,v,cal_json in self.db.execute(query,batch):
                delta=impact_by_path[rid]
                max_abs=max(max_abs,abs(delta));changed_count+=1
                cal=set(json.loads(cal_json))
                if cal & self.protected:
                    protected_any['routes']+=1
                    protected_any['volume']+=v
                    protected_any['volume_weighted_abs_seconds']+=v*abs(delta)
                if driver_idx in cal:
                    label='DRIVER_ON'
                elif cal & self.protected:
                    label='OTHER_PROTECTED_CAL'
                elif cal:
                    label='OTHER_CAL'
                else:
                    label='UNRELATED_TO_CAL'
                obj=groups[label];obj['routes']+=1;obj['volume']+=v
                obj['volume_weighted_abs_seconds']+=v*abs(delta)
                obj['volume_weighted_signed_seconds']+=v*delta
        # Validation observations deliberately do not enter any impact category.
        return {'affected_routes':changed_count,'max_abs_path_seconds':max_abs,
                'by_cal_class':dict(groups),'protected_cal_exposure_including_driver_overlap':protected_any,
                'collateral_to_support_ratio':sum(groups[x]['volume'] for x in
                    ('OTHER_PROTECTED_CAL','OTHER_CAL','UNRELATED_TO_CAL'))/max(driver_support,1e-9),
                'uses_validation_targets':False,'counterfactual_flow_prediction':False}


def contiguous_windows(seq, editable, max_len, preferred=None):
    """Eligible contiguous windows only; may shorten but never stitch separated edges."""
    seq=tuple(seq)
    runs=[];current=[];start=0
    for i,edge in enumerate(seq):
        if edge in editable:
            if not current: start=i
            current.append(edge)
        elif current:
            runs.append((start,tuple(current))); current=[]
    if current:runs.append((start,tuple(current)))
    windows=[]
    for start,run in runs:
        length=min(max_len,len(run))
        if preferred is not None and start <= preferred < start+len(run):
            local=preferred-start
            window_start=max(0,min(local-length//2,len(run)-length))
        else:
            window_start=max(0,(len(run)-length)//2)
        full=run[window_start:window_start+length]
        for part in (full,
                     full[max(0,(len(full)-(max(1,len(full)//2)))//2):][:max(1,len(full)//2)],
                     full[len(full)//2:len(full)//2+1]):
            if part and part not in windows:
                windows.append(part)
    return sorted(windows,key=lambda s:(-len(s),tuple(s)))


def propose_sequence_supply(collector, links, baseline_values, policy, *,
                            sequence_caps=(4,2,1), max_collateral_ratio=None,
                            step_units=(1,)):
    proof=collector.finish()
    if not isinstance(collector,ActualSequenceRouteCollector):
        raise SupplyContractError('SEQUENCE_SOLVER_REQUIRES_EXACT_PATH_STORE')
    units=tuple(integer(x) for x in step_units)
    if not units or any(x < 1 for x in units) or len(set(units)) != len(units):
        raise SupplyContractError('INVALID_ADDVAL_STEP_UNITS')
    if any(x*policy.lattice > policy.max_step+1e-12 for x in units):
        raise SupplyContractError('ADDVAL_STEP_UNITS_EXCEED_MAX_STEP')
    # The schedule is an explicit large-to-small backtracking ladder.  Keeping
    # the caller's order is important; V2.4.9.13 evaluates every selected
    # branch locally from the largest admissible move down to the 5-second
    # lattice step instead of spending the trial budget on unrelated large
    # moves first.
    if list(units) != sorted(units, reverse=True):
        raise SupplyContractError('ADDVAL_STEP_UNITS_NOT_DESCENDING')
    unit_rank={u:i for i,u in enumerate(units)}
    plans=[]; skipped=[]
    editable={key for key,record in links.items() if record.get('eligible') and key in baseline_values}
    for idx in collector.drivers:
        profile=collector.profiles[idx]
        sign=1 if number(profile['model'])>number(profile['observed']) else -1
        coverage=collector.support[idx]/max(1e-30,number(profile['model']))
        if coverage < policy.min_attribution_coverage:
            skipped.append(dict(profile=idx,reason='LOW_ATTRIBUTION_COVERAGE',coverage=coverage))
            continue
        for (kind,orig_seq),ev in sorted(collector.evidence[idx].items(),
                key=lambda item:(-item[1].support,item[0][0],item[0][1])):
            if ev.support <= 0:continue
            direction=sign if kind in ('ON','ON_ONLY_PROBE') else -sign
            orig_seq=tuple(orig_seq)
            hits=[orig_seq.index(k) for k in collector.key_groups[idx] if k in orig_seq]
            pref=min(hits) if hits else None
            for unit in units:
                viable={}
                for edge in orig_seq:
                    if edge not in editable or edge in ev.shared_edges:continue
                    record=links[edge]
                    try:
                        viable[edge]=check_addval_change(edge,record['addval1'],
                            record['addval1']+direction*policy.lattice*unit,
                            baseline_values[edge],record,policy)
                    except SupplyContractError as exc:
                        skipped.append({'profile':idx,'edge':list(edge),'step_units':unit,
                                        'reason':str(exc)})
                for window in contiguous_windows(orig_seq,set(viable),policy.max_edges,preferred=pref):
                    changes=[viable[e] for e in window]
                    plans.append({'driver_index':idx,'kind':kind,'source_sequence':orig_seq,
                        'sequence':window,'anchor_nodes':ev.anchor,
                        'path_pair_example':ev.example,'market_count':ev.markets,
                        'pair_count':ev.pairs,'support_volume':ev.support,
                        'on_volume_witness':ev.on_volume,'off_volume_witness':ev.off_volume,
                        'probe_only':ev.probe,'changes':changes,'coverage':coverage,
                        'step_units':unit,
                        'preference':ev.support*number(profile.get('profile_weight', 1.0))*(1+core.geh(number(profile['model']),number(profile['observed']))/100)})
    # Rank the physical branch first, then retain its complete descending step
    # ladder.  This is the opposite of the pre-V24913 global step-first order.
    plans.sort(key=lambda row:(-row['preference'],row['driver_index'],row['kind'],
                               row['source_sequence'],row['sequence'],unit_rank[row['step_units']]))
    if not plans:
        return {'candidates':[],'skipped':skipped,'authority':proof,
                'selection_mode':'ACTUAL_CONTIGUOUS_SEQUENCES',
                'backtracking_order':'BRANCH_LOCAL_DESCENDING_STEP'}
    # CAP-SPLIT controls the number of *proved* separate branches, not arbitrary links.
    caps=tuple(integer(x) for x in sequence_caps)
    if not caps or any(x<1 for x in caps) or sorted(caps,reverse=True)!=list(caps):
        raise SupplyContractError('INVALID_SEQUENCE_CAP_SPLIT')
    def _combine(seed, cap):
        matched=[seed]
        used={tuple(ch['key']):ch['delta'] for ch in seed['changes']}
        for other in plans:
            if len(matched)>=cap:break
            if other is seed or other['driver_index']!=seed['driver_index']:
                continue
            if other['step_units'] != seed['step_units']:
                continue
            if (other['kind'],other['source_sequence'])==(seed['kind'],seed['source_sequence']):
                continue
            overlap={tuple(ch['key']):ch['delta'] for ch in other['changes']}
            if any(k in used for k in overlap):continue
            if len(used)+len(overlap)>policy.max_edges:continue
            matched.append(other);used.update(overlap)
        return matched

    combinations=[]
    # Generate more raw combinations than the final budget so grouping can keep
    # complete backtracking ladders for the highest-value physical branches.
    raw_seed_limit=min(len(plans),max(10,policy.max_candidates*8))
    for seed in plans[:raw_seed_limit]:
        for cap in caps:
            combinations.append(_combine(seed,cap))

    seen=set(); raw_candidates=[]
    for member in combinations:
        merged={}
        for row in member:
            for change in row['changes']:
                key=tuple(change['key'])
                if key in merged: raise SupplyContractError('INTERNAL_SEQUENCE_OVERLAP')
                merged[key]=change
        changes=[merged[k] for k in sorted(merged)]
        sig=canonical_hash([(row['key'],row['new']) for row in changes])
        if sig in seen:continue
        seen.add(sig)
        driver=member[0]['driver_index']
        support=sum(r['support_volume'] for r in member)
        impact=collector.impact(changes,driver,support)
        if impact['max_abs_path_seconds']>policy.max_bundle_equivalent_seconds+1e-10:
            skipped.append({'candidate':sig[:12],'reason':'ALL_PATH_IMPEDANCE_BUDGET','seconds':impact['max_abs_path_seconds']})
            continue
        if max_collateral_ratio is not None and impact['collateral_to_support_ratio']>number(max_collateral_ratio):
            skipped.append({'candidate':sig[:12],'reason':'COLLATERAL_IMPACT_LIMIT',
                            'ratio':impact['collateral_to_support_ratio']})
            continue
        bundles=[]
        for row in member:
            bundles.append({'kind':row['kind'], 'driver_profile':str(core.first_value(
                collector.profiles[row['driver_index']],('countlocation_no','obs_id','code'))),
                'source_sequence':[list(e) for e in row['source_sequence']],
                'actual_contiguous_sequence':[list(e) for e in row['sequence']],
                'anchor_nodes':list(row['anchor_nodes']),
                'path_pair_example':row['path_pair_example'],
                'support_volume':row['support_volume'],'market_count':row['market_count'],
                'pair_count':row['pair_count'],'probe_only':row['probe_only'],
                'step_units':row['step_units']})
        confidence=('ACTUAL_PATH_PROBE_REQUIRES_NEW_ASSIGNMENT' if any(r['probe_only'] for r in member)
                    else 'EXACT_SAVED_ROUTE_SEQUENCE_CONTRAST_REQUIRES_ASSIGNMENT')
        # Group identity deliberately excludes amplitude/new values.  It is the
        # same proved physical branch bundle at a different backtracking step.
        group_payload={
            'driver_profile':bundles[0]['driver_profile'],
            'bundles':[(b['kind'],b['source_sequence'],b['actual_contiguous_sequence']) for b in bundles],
            'change_keys_and_signs':[(row['key'],1 if row['delta']>0 else -1) for row in changes],
        }
        group_id='BRANCH_'+canonical_hash(group_payload)[:16]
        branch_preference=sum(float(r['preference']) for r in member)
        raw_candidates.append({'candidate_id':'SEQUENCE_'+sig[:12],
            'kind':'ACTUAL_PATH_SEQUENCE_BUNDLE',
            'parent_hash':collector.parent_hash,
            'assignment_path_hash':proof['assignment_path_hash'],
            'driver_profile':bundles[0]['driver_profile'],
            'changes':changes,'bundles':bundles,'sequence_cap':len(member),
            'step_units':member[0]['step_units'],
            'backtracking_group_id':group_id,
            'backtracking_step_rank':unit_rank[member[0]['step_units']],
            'branch_preference':branch_preference,
            'confidence':confidence,'all_path_impact':impact,
            'impact_audit_basis':'ALL_SAVED_ACTUAL_PATHS_NO_VALIDATION_TARGETS',
            'equivalent_impedance_budget_seconds':impact['max_abs_path_seconds']})

    grouped=defaultdict(list)
    for candidate in raw_candidates:
        grouped[candidate['backtracking_group_id']].append(candidate)
    group_order=sorted(grouped,
        key=lambda gid:(-max(x['branch_preference'] for x in grouped[gid]),
                        min(x['driver_profile'] for x in grouped[gid]),gid))
    candidates=[]; complete_groups=[]
    for gid in group_order:
        rows=sorted(grouped[gid],key=lambda x:(x['backtracking_step_rank'],-x['sequence_cap'],x['candidate_id']))
        # Deduplicate same amplitude/cap variants while preserving the strongest
        # proved branch bundle at each step.
        selected=[]; seen_steps=set()
        for row in rows:
            step=row['step_units']
            if step in seen_steps:continue
            selected.append(row);seen_steps.add(step)
        if len(candidates)+len(selected)>policy.max_candidates:
            # Never publish a partial ladder.  The controller can therefore
            # interpret candidate adjacency as true branch-local backtracking.
            continue
        rank=len(complete_groups)+1
        for row in selected:
            row['backtracking_group_rank']=rank
        candidates.extend(selected)
        complete_groups.append({'group_id':gid,'rank':rank,
                                'step_units':[x['step_units'] for x in selected],
                                'candidate_ids':[x['candidate_id'] for x in selected]})
        if len(candidates)>=policy.max_candidates:break
    return {'candidates':candidates,'skipped':skipped,'authority':proof,
            'selection_mode':'ACTUAL_CONTIGUOUS_SEQUENCES','cap_schedule':list(caps),
            'step_units_schedule':list(units),
            'backtracking_order':'BRANCH_LOCAL_DESCENDING_STEP',
            'complete_backtracking_groups':complete_groups,
            'source_sequence_count':sum(len(x) for x in collector.evidence.values())}
