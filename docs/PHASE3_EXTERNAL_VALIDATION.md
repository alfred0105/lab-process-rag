# Phase 3 External Scientific Validation

**Status: `EXTERNAL_VALIDATION_PENDING`**. Synthetic fixtures and software regression tests do not establish measurement accuracy or real-process scientific validity.

| Validation area | Required external evidence | Independent reference / metadata | Approval or safety conditions |
|---|---|---|---|
| ZnO XRD phase/peak interpretation | Original instrument files from representative ZnO samples, including mixtures and low-signal/background cases | Instrument, radiation target and calibrated wavelength, geometry, reference standard, sample prep, expert-reviewed phase assignment or certified standard | Researcher authorizes dataset use; reference labels must be independent of the app output |
| AFM height/roughness | Original height-map files from representative specimens | X/Y scan dimensions, z calibration, tip/instrument metadata, scan settings, traceable reference surface, independent roughness result | Preserve unmodified originals and disclose leveling/filtering settings |
| SEM/TEM segmentation and measurements | Representative original images across magnification, contrast and particle overlap | Pixel calibration or scale bar, acquisition metadata, independently reviewed masks and object counts/sizes | No material identification claims from exploratory thresholding; labels reviewed by a domain expert |
| PHREEQC vs actual solution chemistry | Prepared solutions with measured pH and, where relevant, analytical concentrations/speciation proxies across controlled conditions | Reagent hydrate/purity, masses, volumes, temperature, calibration and measurement uncertainty; documented database selection | Chemical handling and sampling follow the lab's approved procedures; simulated saturation is not proof of precipitation |
| OpenFOAM CFD | A supported, geometry-specific case with successful convergence | Solver/version, mesh and mesh-independence evidence, boundary/initial conditions, residuals, conservation checks, tracer or velocity reference | Explicit researcher approval before execution; approved VM/compute target; never run against production records by default |
| CFD to physical experiment comparison | Matched mixer vessel, magnetic bar or process geometry, with repeat measurements | RPM, vessel/bar geometry, fluid density/viscosity/temperature, tracer mixing curves or equivalent physical measurements | Separate predictive uncertainty from measured uncertainty; document deviations and failed runs |
| Real equipment control | Instrument-specific protocol, interlocks and failure behavior | Vendor interface, calibration history, command audit and dry-run evidence | Formal safety review and explicit human approval; not implemented by Phase 3 core |

For each study, retain source files, hashes, processing parameters, units, calibration, independent ground truth, uncertainty and reviewer records. Do not promote literature/simulation/synthetic rows into accepted experimental observations.
