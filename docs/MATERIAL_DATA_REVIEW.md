# Material data review in simulations

## User flow

1. Select a saved, non-demo experiment run in the Simulation workspace.
2. The deterministic saved-input check identifies PHREEQC requirements, conditional OpenFOAM mixer fields, and material record gaps. This report, not Gemma, is authoritative for whether a saved value exists.
3. Ask the configured local Gemma model to explain why missing data matter and ask for known values to be entered in the process record; unknown values can remain blank. PHREEQC and OpenFOAM mixer inputs remain conditional on choosing those calculations.
4. When Gemma reports a material-related information gap, the app looks up up to four recorded material identities through PubChem and searches up to two suggested literature queries in Crossref.
5. PubChem identity lookup also searches NIST Chemistry WebBook by the recorded material name and shows the matching record title and data-section links when present. This is source discovery only; the app does not parse NIST property values into an experiment or simulator input.
6. The app displays source records and limitations. Search results never overwrite an experiment, saved method, material, or measurement.
7. Known PHREEQC and optional mixer values can be entered in the same panel and saved as new conditions under a selected process step. Existing non-empty conditions are protected from overwrite. Exact material names and known amounts can be appended separately to the experiment's material list. The PHREEQC workbench reads the added conditions on its next refresh.

## Source boundaries

- PubChem PUG REST is used for candidate chemical identity fields such as formula, molecular weight, IUPAC name, and InChIKey.
- NIST Chemistry WebBook name search supplies record and section links for user inspection. The app does not claim to extract a particular NIST value automatically. NIST data availability depends on the compound and property.
- Crossref is used for scholarly metadata and DOI discovery only. A result becomes research evidence only after the user adds and indexes an accessible full-text PDF in the existing paper workflow.
- PubChem identity records cannot establish supplier, lot, hydration state as supplied, purity, stock concentration, measured density/viscosity, or the actual contents of a user's vessel. Confirm the reagent against its label and certificate of analysis.
- Missing values remain missing. The user can enter known values or leave them blank; no generic value is silently substituted.

## Model boundary

Gemma reviews the selected process record and explains why information is needed. Its suggestions are labeled MODEL_KNOWLEDGE, carry no paper citation, and are filtered when they contradict the deterministic saved-field check. They are not experimental measurements and cannot establish that a simulation is scientifically valid. The deterministic PHREEQC input checks remain responsible for enforcing required pH, temperature, supported dissolved totals, and units. OpenFOAM's packaged mixer tutorial is only an installation check; converting a user's vessel, impeller, feed, fluid properties, and process values into and running a validated CFD case remains future work.

## Official source references

- [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest)
- [NIST Chemistry WebBook](https://webbook.nist.gov/chemistry/)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
