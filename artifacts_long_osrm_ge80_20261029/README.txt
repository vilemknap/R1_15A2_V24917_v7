LONG OD mask from OSRM matrix 9697 / R1_OSRM_DIST_KM.
Rule: 1 if distance >= 80 km, otherwise 0. No upper distance limit.
681 x 681; 74,966 allowed directed OD pairs.
ZIP contains the Visum .mtx mask, compressed NumPy mask with zone numbers, and metadata.
Source matrix is unchanged. The mask is not yet applied to native TD.
LONG_COMPOSITE shared-parameter preparation is included in this branch; live LONG remains disabled pending native support and count-response validation.
