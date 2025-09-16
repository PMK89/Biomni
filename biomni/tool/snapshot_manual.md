# Handbuch: Manuelles Erstellen einer Snapshot-Datei

Eine Snapshot-Datei ist eine **UTF-8 JSON-Datei**, die den minimalen Informationssatz speichert, um ein Projekt in PK-Sim® oder MoBi® neu aufzubauen.
Sie dient der **Versionen-übergreifenden Migration** und als **leicht verständliches Austauschformat**.

---

## 1. Grundstruktur

Jede Snapshot-Datei hat eine feste Grundstruktur mit fünf Hauptkomponenten:

```json
{   "Version": 74,   "Individuals": [],   "Populations": [],   "Compounds": [],   "Protocols": [],   "Simulations": [] }
```

* `Version`: Software-Versionskennung (z. B. 74 für OSP v12.0).
* Die Arrays enthalten die Projektbausteine.

---

## 2. Individuen (`Individuals`)

Ein **Individuum** beschreibt eine einzelne virtuelle Person.

### Beispiel

```json
"Individuals": [   {     "Name": "StandardMale",     "Age": 30,     "Weight": 70,     "Height": 175,     "Sex": "Male"   } ]
```

### Einstellmöglichkeiten

| Schlüssel           | Beschreibung                 | Beispiel                          |
| ------------------- | ---------------------------- | --------------------------------- |
| `Name`              | Name des Individuums         | `"StandardMale"`                  |
| `Age`               | Alter (Jahre)                | `30`                              |
| `Weight`            | Körpergewicht (kg)           | `70`                              |
| `Height`            | Körpergröße (cm)             | `175`                             |
| `Sex`               | Geschlecht                   | `"Male"` oder `"Female"`          |
| `BMI`               | Body Mass Index (optional)   | `22.8`                            |
| `OrganVolumes`      | Individuelle Organvolumina   | `{ "Liver": 1.5, "Kidney": 0.3 }` |
| `ExpressionProfile` | Enzym-/Transporterexpression | `{ "CYP3A4": 1.2 }`               |

---

## 3. Populationen (`Populations`)

Eine **Population** ist eine Sammlung von Individuen, die nach bestimmten Regeln erzeugt wird.

### Beispiel

```json
"Populations": [   {     "Name": "AdultPopulation",     "Size": 100,     "Seed": 12345,     "AgeRange": [18, 65],     "SexRatio": {"Male": 0.5, "Female": 0.5}   } ]
```

### Einstellmöglichkeiten

| Schlüssel            | Beschreibung                                | Beispiel                         |
| -------------------- | ------------------------------------------- | -------------------------------- |
| `Name`               | Name der Population                         | `"AdultPopulation"`              |
| `Size`               | Anzahl Individuen                           | `100`                            |
| `Seed`               | Zufallszahl-Seed (Reproduzierbarkeit)       | `12345`                          |
| `AgeRange`           | Altersbereich                               | `[18, 65]`                       |
| `SexRatio`           | Geschlechterverteilung                      | `{ "Male": 0.5, "Female": 0.5 }` |
| `WeightDistribution` | Gewichtsspanne                              | `[50, 100]`                      |
| `ExpressionProfile`  | Verteilung von Enzym-/Transporterexpression | `{ "CYP2D6": "bimodal" }`        |

---

## 4. Substanzen (`Compounds`)

Ein **Compound** definiert die physikochemischen, ADME- und PK-Eigenschaften einer Substanz.

### Beispiel (kurz)

```json
"Compounds": [   {     "Name": "DrugX",     "MolecularWeight": 300.4,     "LogP": 2.3,     "FractionUnbound": 0.05,     "Solubility": {"Value": 0.01, "Unit": "mg/mL"}   } ]
```

### Einstellmöglichkeiten

#### Allgemein

| Schlüssel         | Beschreibung           | Beispiel                           |
| ----------------- | ---------------------- | ---------------------------------- |
| `Name`            | Substanzname           | `"DrugX"`                          |
| `MolecularWeight` | Molekulargewicht       | `300.4`                            |
| `LogP`            | Lipophilie             | `2.3`                              |
| `FractionUnbound` | Ungebundener Anteil    | `0.05`                             |
| `Solubility`      | Löslichkeit            | `{"Value": 0.01, "Unit": "mg/mL"}` |
| `pKaValues`       | Säure-/Basenkonstanten | `[4.5, 8.1]`                       |
| `BileSaltEffect`  | Einfluss der Galle     | `true`                             |

#### Absorption

| Schlüssel                | Beschreibung            | Beispiel       |
| ------------------------ | ----------------------- | -------------- |
| `IntestinalPermeability` | Permeabilität im Darm   | `1.2e-4`       |
| `EffectivePermeability`  | Effektive Permeabilität | `5.6e-5`       |
| `AbsorptionModel`        | Modell                  | `"FirstOrder"` |
| `StomachEmptyingTime`    | Entleerungszeit (h)     | `0.5`          |

#### Distribution

| Schlüssel                    | Beschreibung               | Beispiel             |
| ---------------------------- | -------------------------- | -------------------- |
| `PartitionCoefficientMethod` | Methode                    | `"RodgersRowland"`   |
| `TissueBinding`              | Gewebe-spezifische Bindung | `{ "Liver": 0.8 }`   |
| `PlasmaProteinBinding`       | Proteinbindung             | `{ "Albumin": 0.9 }` |

#### Metabolismus

| Schlüssel          | Beschreibung        | Beispiel                                           |
| ------------------ | ------------------- | -------------------------------------------------- |
| `ClearanceMethods` | Clearancearten      | `{ "ClInt_hepatic": 25.0 }`                        |
| `EnzymeKinetics`   | Kinetik (Km, Vmax)  | `[{"Enzyme": "CYP3A4", "Km": 2.5, "Vmax": 50}]`    |
| `Inhibition`       | Hemmparameter       | `[{"Enzyme": "CYP2D6", "Ki": 0.2}]`                |
| `Induction`        | Induktionsparameter | `[{"Enzyme": "CYP1A2", "Emax": 2.0, "EC50": 1.5}]` |

#### Transporter

| Schlüssel                 | Beschreibung                 | Beispiel                                                                |
| ------------------------- | ---------------------------- | ----------------------------------------------------------------------- |
| `TransporterInteractions` | Transporter-Wechselwirkungen | `[{"Transporter": "OATP1B1", "Type": "Uptake", "Km": 10, "Vmax": 100}]` |
| `TransporterInhibition`   | Transporterhemmung           | `[{"Transporter": "BCRP", "Ki": 0.5}]`                                  |
| `TransporterInduction`    | Transporterinduktion         | `[{"Transporter": "P-gp", "Emax": 1.5, "EC50": 2.0}]`                   |

---

## 5. Protokolle (`Protocols`)

Ein **Protokoll** beschreibt, wie eine Substanz verabreicht wird.

### Beispiel: IV-Bolus

```json
"Protocols": [   {     "Name": "IVBolus10mg",     "Type": "Bolus",     "Dose": {"Value": 10, "Unit": "mg"},     "Route": "Intravenous",     "StartTime": 0   } ]
```

### Einstellmöglichkeiten

| Schlüssel          | Beschreibung            | Beispiel                                    |
| ------------------ | ----------------------- | ------------------------------------------- |
| `Name`             | Protokollname           | `"IVBolus10mg"`                             |
| `Type`             | Applikationsart         | `"Bolus"`, `"Oral"`, `"Infusion"`           |
| `Dose`             | Dosis                   | `{"Value": 100, "Unit": "mg"}`              |
| `Route`            | Applikationsweg         | `"Intravenous"`, `"Oral"`, `"Subcutaneous"` |
| `Interval`         | Dosierungsintervall (h) | `12`                                        |
| `NumberOfDoses`    | Anzahl Gaben            | `10`                                        |
| `InfusionDuration` | Dauer (h)               | `1`                                         |

---

## 6. Simulationen (`Simulations`)

Eine **Simulation** verbindet Individuum/Population, Compound und Protokoll.

### Beispiel

```json
"Simulations": [   {     "Name": "DrugX_SingleDose",     "Individual": "StandardMale",     "Compound": "DrugX",     "Protocol": "IVBolus10mg",     "Duration": 24,     "Outputs": ["Plasma (PeripheralVenousBlood)", "Liver"]   } ]
```

### Einstellmöglichkeiten

| Schlüssel    | Beschreibung              | Beispiel              |
| ------------ | ------------------------- | --------------------- |
| `Name`       | Name der Simulation       | `"DrugX_SingleDose"`  |
| `Individual` | Referenz auf Individuum   | `"StandardMale"`      |
| `Population` | Referenz auf Population   | `"AdultPopulation"`   |
| `Compound`   | Verwendete Substanz       | `"DrugX"`             |
| `Protocol`   | Verknüpftes Protokoll     | `"IVBolus10mg"`       |
| `Duration`   | Simulationsdauer (h)      | `24`                  |
| `Outputs`    | Liste gewünschter Outputs | `["Plasma", "Liver"]` |

---

# Komplettes Beispiel

```json
{   "Version": 74,   "Individuals": [     {       "Name": "StandardMale",       "Age": 30,       "Weight": 70,       "Height": 175,       "Sex": "Male"     }   ],   "Populations": [],   "Compounds": [     {       "Name": "DrugX",       "MolecularWeight": 300.4,       "LogP": 2.3,       "FractionUnbound": 0.05,       "Solubility": {"Value": 0.01, "Unit": "mg/mL"},       "pKaValues": [4.5, 8.1],       "PartitionCoefficientMethod": "RodgersRowland",       "ClearanceMethods": {"ClInt_hepatic": 25.0},       "EnzymeKinetics": [         {"Enzyme": "CYP3A4", "Km": 2.5, "Vmax": 50}       ]     }   ],   "Protocols": [     {       "Name": "IVBolus10mg",       "Type": "Bolus",       "Dose": {"Value": 10, "Unit": "mg"},       "Route": "Intravenous",       "StartTime": 0     }   ],   "Simulations": [     {       "Name": "DrugX_SingleDose",       "Individual": "StandardMale",       "Compound": "DrugX",       "Protocol": "IVBolus10mg",       "Duration": 24,       "Outputs": ["Plasma (PeripheralVenousBlood)", "Liver"]     }   ] }
```

---

✅ Damit haben Sie ein **komplettes Handbuch mit Referenz-Tabellen und Beispiel**, mit dem sich jede Snapshot-Datei manuell erstellen lässt.
