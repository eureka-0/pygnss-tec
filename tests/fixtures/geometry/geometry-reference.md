The CSV values were generated with pymap3d 3.2.0, NumPy 2.5.4 and WGS84 using Float64 coordinates.
Columns contain the complete inputs and reference outputs for independent regression checks.

The controls include varied observers and heights, wrapped longitudes, poles, axes, the Earth centre, interior points, coincident targets, ENU components on both sides of the 1 mm zero threshold, and NaN/infinity conventions.
The angle tolerance is 1e-11 degrees and the height tolerance is 5e-8 metres.
Independent equatorial ENU controls exercise uniform observers, the bounded cache fallback, parallel batches and partitioned inputs.

`cibg.csv` freezes GPS and BeiDou geometry for the bundled CIBG observations and IGS navigation on 2024-01-10, computed with the previous orbit propagation and angle conversion. Both Polars engines exercise these controls.
