# V2.4.8.1 real-run postmortem → CP12

V2.4.8.1 failed safely on `NATIVE_CW 1→7` after a forced fresh enumeration. The refreshed epoch returned the same exact/comparison/structure hashes as the restored epoch, so re-enumeration did not and could not create a route share for this relation.

For `NATIVE_CW`, live interzonal matrix volume was 115805.3321426331 while saved path interzonal volume was 115793.589. The residual was 11.7431426331 vehicles, relative 0.0001014042, far inside the already-authorized 0.01 path-volume parity tolerance.

CP12 therefore distinguishes two cases: truly missing geometry still forces re-enumeration; existing geometry with zero saved DSeg share is excluded from proposal-path incidence only when the aggregate DSeg residual is within the existing parity contract. The OD amount remains in projection base marginals, and every candidate still requires a fresh Visum assignment plus live 12D/11D acceptance. No route split is invented.
