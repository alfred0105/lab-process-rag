# Cross-disciplinary experiment method catalog

## Scope

There is no finite list of every experimental method: laboratories combine instruments, sample types, and protocols, and introduce new variants. The application should therefore use an extensible catalog of method templates, plus a custom method option. Templates provide editable process-map scaffolding only. They must not prescribe universal numerical conditions.

This catalog is intended to work across materials science, chemistry, biology, engineering, environmental work, and computational research. Users choose a topic workspace first; each workspace can add local techniques without mixing its experiments, papers, or Gemma context with another workspace.

## Research basis

This review covered 78 Exa search results across eight searches, then fetched institutional or primary sources for closer review. Facility capability catalogs are useful for discovering method families, while the ISA specification provides a stronger model for how to record experiments. This is a broad starting survey, not a claim that every technique in science has been enumerated.

The [ISA model and serialization specification](https://isa-specs.readthedocs.io/en/latest/isamodel.html) represents experimental work as an Investigation, Study, and one or more Assays. Its process graphs connect materials, processes, samples, and data, and are directed and acyclic. This is a sound basis for a map UI that can later support more than a simple list of steps. The [ISA overview](https://isa-specs.readthedocs.io/en/latest/) emphasizes sample characteristics, technology and measurement types, and sample-to-data relationships.

The [MIT Data Management and Analysis Core assay catalog](https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/reference/assays) defines an assay through its input sample type, generated data type, and procedure. That input-to-output relationship is useful for connecting an experimental process node to result files and structured measurements.

The [NIH reporting principles](https://grants.nih.gov/policy-and-compliance/policy-topics/reproducibility/principles-guidelines-reporting-preclinical-research) call out replicates, sample provenance, randomization, blinding, sample-size planning, and complete statistical reporting. Not every field applies to every experiment, so the interface should make these optional and method-specific rather than force one universal form.

Institutional catalogs show why the method library must span domains: [NLR Materials Science](https://www.nlr.gov/materials-science/materials-characterization) includes composition, structure, optical, electrical, and surface characterization; [RTNN](https://rtnn.ncsu.edu/facilities/) includes lithography, deposition, etching, thermal processing, microscopy, and metrology; [UMass Core Facilities](https://www.massachusetts.edu/research/core-facilities/core-facilities-capabilities) spans life sciences, chemistry, material science, nanofabrication, manufacturing, and engineering.

## Proposed method families

| Family | Example techniques | Useful output types |
| --- | --- | --- |
| Synthesis and sample preparation | Solution mixing, hydrothermal growth, sol-gel, precipitation, solid-state reaction, electrospinning | New sample or material, batch notes, yield, sample identifiers |
| Coating, fabrication, and patterning | Spin/dip/drop coating, sputtering, evaporation, CVD, ALD, photolithography, wet/dry etching, additive manufacturing | Film, device, patterned sample, image or geometry file |
| Thermal and environmental treatment | Annealing, calcination, curing, corrosion, humidity/temperature exposure, cycling tests | Before/after sample, condition log, property change |
| Imaging and microscopy | Optical microscopy, XRD, XRF, AFM, SEM/EDS, TEM/STEM, XPS, Raman, FTIR, UV-Vis, photoluminescence | Images, spectra, diffraction patterns, maps, identified features |
| Chemical analysis and separation | HPLC/GC, LC-MS, NMR, ICP-OES/MS, titration, TGA/DSC | Chromatograms, spectra, composition, concentration, thermal curves |
| Biological and biochemical assays | Cell culture/treatment, PCR/qPCR, sequencing, flow cytometry, ELISA/plate assays, Western blot, viability assays | Images, amplification curves, sequence files, counts, intensities |
| Mechanical and electrical properties | Tensile/compression, hardness/indentation, rheology, I-V/four-point probe, impedance, magnetometry | Curves, maps, fitted parameters, repeated measurements |
| Field and environmental studies | Field sampling, sensor deployment, exposure/monitoring, water or soil measurements | Time series, location/sample records, field notes, lab analysis |
| Computational and data analysis | Simulation, parameter sweep, image/spectrum processing, statistical analysis | Input dataset, code/configuration, model output, validation results |
| Custom | User-defined procedure or instrument method | User-defined files and measurements |

The current catalog exposes 51 technique templates across ten searchable categories, plus a custom method option. A template seeds a reusable process map, method-specific condition fields, and suggested material slots. It never pre-fills scientific setting values. Users can revise a method by creating a new version, leaving earlier runs attached to the version they used.

## Shared experiment record

Keep a compact common record and let each method add fields as needed:

- Workspace and experiment identity, title, objective, date, operator, status, and notes.
- Sample/material identity, source or batch, preparation, and parent/derived sample links where applicable.
- Process-map nodes, directed links, protocol/method, actual conditions and units, equipment/platform, and deviations.
- Controls, standards, calibration, replicates, randomization, blinding, and exclusion rules when applicable.
- Result values with units, measurement method, raw file, derived file, and provenance.
- Separate measured data, direct observations, computed outputs, and interpretations.
- Source labels so Gemma can distinguish a paper excerpt, a recorded experiment fact, a deterministic calculation, and its own general knowledge.

## UI and Gemma design

1. Select a research topic from the top-level home page. Experiments, indexed papers, evidence search, and instrument-analysis runs are filtered to that topic.
2. In the topic, create a reusable method from a curated template or from a blank custom map. Define process nodes, each node's condition fields, and required material slots once.
3. Create a run from a selected method version. The method structure stays fixed while the operator enters actual condition values, material amounts and batch details, measurements, and observations.
4. Runs receive backend-generated sequence numbers under their method. To change the procedure, create a new method version; prior runs remain attached to the version used.
5. For Gemma, serialize the selected run and its method/version as short ordered plain text. Retrieval is scoped to the active research topic. Do not send a screenshot of the map.

The current prototype stores each method map as an ordered linear sequence. It can display a connected flow, but branching sample provenance and links between multiple assays require a graph-aware backend schema before claiming full ISA-style graph support. Existing experiment records are migrated into a legacy topic and grouped under shared method drafts when their recorded process schemas match.

## Saved materials

Each research topic has a reusable material library. Add a material once with its role, default unit, supplier, catalog number, and notes; then select it while composing a method or recording a run. A run can also save a newly typed material to the library for later use. Existing experiment material entries are imported into the matching topic library by material name, without changing the original run records.
