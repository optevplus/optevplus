### 12 points, scenario base, island-wide (from Postgres)

| Method | Points | Drivers rescued / h | Per point | vs best baseline | Violations | Runtime ms |
|---|---|---|---|---|---|---|
| random (mean of 100) | 12 | 1.902 ± 0.253 | 0.158 | 0.53× | 0 | 48.7 |
| population share | 12 | 2.745 | 0.229 | 0.77× | 0 | 1.2 |
| optimiser (CP-SAT) | 12 | 3.708 | 0.309 | 1.04× | 0 | 162.7 |
| busiest first (#36) | 12 | 3.572 | 0.298 | 1.00× | 0 | 2.6 |
| spatial spread (#37) | 12 | 3.400 | 0.283 | 0.95× | 0 | 1504.3 |
| extend existing (#38) | 12 | 0.405 | 0.034 | 0.11× | 0 | 2.1 |

### 50 points, scenario base, island-wide (from Postgres)

| Method | Points | Drivers rescued / h | Per point | vs best baseline | Violations | Runtime ms |
|---|---|---|---|---|---|---|
| random (mean of 100) | 50 | 8.006 ± 0.496 | 0.160 | 0.59× | 0 | 54.5 |
| population share | 50 | 10.153 | 0.203 | 0.75× | 0 | 1.0 |
| optimiser (CP-SAT) | 50 | 15.021 | 0.300 | 1.11× | 0 | 266.2 |
| busiest first (#36) | 50 | 9.836 | 0.197 | 0.73× | 0 | 2.8 |
| spatial spread (#37) | 50 | 13.524 | 0.270 | 1.00× | 0 | 1534.1 |
| extend existing (#38) | 50 | 3.657 | 0.073 | 0.27× | 0 | 2.0 |

### 100 points, scenario base, island-wide (from Postgres)

| Method | Points | Drivers rescued / h | Per point | vs best baseline | Violations | Runtime ms |
|---|---|---|---|---|---|---|
| random (mean of 100) | 100 | 15.984 ± 0.711 | 0.160 | 0.61× | 0 | 65.4 |
| population share | 100 | 18.834 | 0.188 | 0.72× | 0 | 1.0 |
| optimiser (CP-SAT) | 100 | 29.529 | 0.295 | 1.12× | 0 | 329.1 |
| busiest first (#36) | 100 | 13.267 | 0.133 | 0.50× | 0 | 2.5 |
| spatial spread (#37) | 100 | 26.338 | 0.263 | 1.00× | 0 | 1582.8 |
| extend existing (#38) | 100 | 9.254 | 0.093 | 0.35× | 0 | 2.1 |
