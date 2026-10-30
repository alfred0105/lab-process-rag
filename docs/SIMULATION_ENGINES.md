# Simulation engines connected to Lab Process RAG

Updated 2026-10-29. The application marks measured values, deterministic calculations, thermodynamic estimates, and historical analogs separately.

## Available locally

| Tool | What it calculates | Main limits |
| --- | --- | --- |
| Local ideal acid/base estimator | Bounded pH estimate for its listed reagent set | Simplified dilute-solution assumptions; not speciation or precipitation |
| PHREEQC 3 (`phreeq.dat`) through `phreeqpython` 1.6.2 | Aqueous species distributions and selected mineral saturation indices; fixed-total pH sweep | Requires appropriate database and charge-balanced analytical totals. Saturation is not proof of precipitation and does not predict nucleation, morphology, growth rate, or yield |
| Historical-run analog | Transparent weighted average of the three nearest recorded runs for one selected condition in a method version | Requires at least three matching completed records and interpolation within observed range. It is not a validated physical model, causal estimate, confidence interval, or success probability |
| XRD peak candidate analysis | Peak detection and candidate structure pattern matching | A measurement-analysis workflow, not a process simulator; candidates require scientific review |

PHREEQC is installed in `backend/.venv` with a 2.1 MB Apple Silicon wheel on the current MacBook Air M5 / 24 GB / macOS 27 environment. `GET /api/simulations/status` now detects the local Multipass OpenFOAM 14 VM as installed; it does not imply a process mixing case is connected. The PHREEQC endpoints are local: `POST /api/simulations/aqueous-equilibrium`; pH sweep: `POST /api/simulations/aqueous-equilibrium/sweep`; stirred batch dose path: `POST /api/simulations/stirred-reaction-path`. The stirred path treats each cumulative HCl/NaOH dose as a homogeneous equilibrium point; it is not a mixing-rate or kinetic simulation.

## Local engines and current execution state

- **OpenFOAM 14**: installed in the Apple Silicon Ubuntu 24.04 Multipass VM `lab-rag-openfoam` (6 vCPU, 8 GB RAM, 60 GB virtual disk). A copied official `incompressibleFluid/simpleRushtonMRF` tutorial completed a 20 s solver smoke run locally (`blockMesh`, `createZones`, stirrer/baffle generation, `foamRun`, final `End`); at 10 s output interval it emitted three finite integrated-power rows and tutorial power number 3.08. This validates the installed solver/template output path only; it is not a literature-data validation or an experimental prediction. The application now has a strict process-record compatibility plan, non-demo-only launch/status/history APIs, separate persistent simulation records, and an HTML power-trace view. Launch is blocked until the record has supported vessel/impeller geometry, baffles, fully filled/closed vessel, matching liquid volume, RPM, density, and viscosity. The full application-parameterized 4,000 s case has **not yet** been run on a qualifying recorded experiment; no current literature record supplies all required Rushton geometry and fluid properties. See [the solution-mixing model scope and implementation plan](SOLUTION_MIXING_SIMULATION_PLAN.md).
- **Magnetic stir bar**: not implemented as a solver case. The current compatibility checker now identifies it as unsupported by the Rushton case and blocks execution. A separate open-beaker bar model needs its own geometry, rotation/free-surface assumptions, and measured mixing validation; see [the magnetic stir-bar simulation plan](MAGNETIC_STIR_BAR_SIMULATION_PLAN.md).
- Completed simulation records can now be selected by a research-topic synthesis. Gemma receives solver output in a separate field from instrument measurements and can cite it only as `SIMULATION_OUTPUT` with the exact simulation-run ID. Synthetic demo experiments are excluded from topic synthesis, and literature `reference` records cannot be used as LAB_PATTERN outcome examples. No completed application CFD record currently exists.
- **Cantera**: available as a future integration candidate for open-source thermochemistry, chemical kinetics, and transport. It fits reaction mechanisms such as gas-phase/CVD systems when a suitable mechanism and parameters are supplied; it cannot infer a validated ZnO nanowire growth mechanism from process labels alone.
- **LAMMPS**: open-source molecular dynamics for atomistic/material simulations. It can run small CPU jobs on this Mac, but useful material predictions require an appropriate validated interatomic potential, structure, and boundary conditions; runtime depends heavily on system size.
- **Reaktoro**: open-source chemical equilibrium and kinetics, with an Apple Silicon conda-forge package. It overlaps PHREEQC's aqueous/mineral chemistry role and is not added as a second engine until a concrete workflow needs its capabilities.

## Sources

- USGS PHREEQC 3 software and downloads: <https://www.usgs.gov/software/phreeqc-version-3>
- USGS PHREEQC capabilities and model documentation: <https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-2.htm>
- PhreeqPython source, usage, and license: <https://github.com/Vitens/phreeqpython>
- Cantera official overview: <https://cantera.org/>
- LAMMPS official macOS installation: <https://docs.lammps.org/stable/Install_mac.html>
- Reaktoro macOS ARM package listing: <https://anaconda.org/conda-forge/reaktoro>
- OpenFOAM official macOS/Apple Silicon installation guidance: <https://openfoam.org/download/14-macos/>
- OpenFOAM 14 official Ubuntu package installation: <https://openfoam.org/download/14-ubuntu/>
- OpenFOAM standard solver list (`twoLiquidMixingFoam`, `scalarTransportFoam`): <https://www.openfoam.com/documentation/user-guide/a-reference/a.1-standard-solvers>
- Mixing and precipitation subprocesses review: <https://www.jstage.jst.go.jp/article/kona/33/0/33_2016021/_html/-char/en>
