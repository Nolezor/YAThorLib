# Support coverage

Hardware evidence so far: KDC101 with an MTS100/M-Z8 stage, read, enable, home, relative and absolute moves, stop and raw status updates (see [validation.md](validation.md)); nothing else has been hardware-qualified. “Typed” below means selected payloads and operations have an implementation and synthetic tests, not full coverage of that device. Raw catalog availability means that a caller must supply and interpret the packet body. Firmware and stage configuration can affect applicability.

| API | Selected coverage | Remaining limitations |
| --- | --- | --- |
| Motor | Position, explicit DC/stepper status layouts, home, absolute/relative moves, jog, stop; common parameter layouts | No automatic stage settings or conversion; specialized filter flipper, polarizer, brushless and voice-coil functions need raw access |
| Piezo | Raw voltage/position, control mode and selected parameters | Model-specific precision and trigger functions incomplete |
| InertialMotor | KIM101/TIM101 position, absolute motion, stop, raw subparameters | Channel masks are 1/2/4/8; stop completion handling and other subparameter layouts incomplete |
| PiezoStage | PDXC2/PDXC3 parameter envelope | Model-specific payloads require raw access |
| Solenoid | State, operating mode and cycle parameters | Trigger and MMI configuration require raw access |
| StrainGauge | Raw strain readings | Physical conversion depends on display mode/calibration |
| NanoTrak | Readings, tracking mode/threshold, circle home and status | Remaining configuration requires raw access |
| Laser | Output enable/disable, raw parameter envelope | No typed current/power conversions or limits |
| TemperatureController | Raw setpoint and readings, parameter envelope | Sensor-dependent temperature conversion is not guessed |
| QuadDetector | Detector readings, raw parameter envelope | Additional feedback/configuration requires raw access |
| LiquidCrystal | KLC101 preset voltage/frequency read/write from native evidence | Experimental; operating mode and status not implemented |
| PositionReadoutEncoder | Position and zero from native evidence | Experimental; use explicit family name `PositionReadoutEncoder`; display, calibration and status not implemented |
| Rack | Occupied bays and endpoint addressing | No native Ethernet hub negotiation |
| Device/Connection | Documented model command lookup and arbitrary APT framing | No automatic payload codec for every command |

## PDF applicability groups

These are the extracted document headings, not a hardware certification list. `commands_for(model)` returns exact outgoing command names; `device(model)` selects a convenience class based on that set. An unknown model is rejected rather than assigned an inferred protocol. Lowercase `x` in a source heading matches a single digit.

| Document applicability heading | Catalog names |
| --- | ---: |
| Messages Applicable to BPC20x Series | 54 |
| Messages Applicable to BPC30x Series | 56 |
| Messages Applicable to PPC001 and PPC102 | 46 |
| Messages Applicable to TPZ001 and KPZ101 | 38 |
| Messages Applicable to KPZ101 Only | 6 |
| Messages Applicable to KPC101 | 59 |
| Messages Applicable to TSG001 and KSG101 | 27 |
| Messages Applicable to KSG101 Only | 6 |
| Messages Applicable to MPZ601 | 50 |
| Messages Applicable to TDC001 and KDC101 | 69 |
| Messages Applicable to KDC101 Only | 3 |
| Messages Applicable to KVS30 | 62 |
| Messages Applicable to TSC001 and KSC101 | 36 |
| Messages Applicable to KSC101 Only | 3 |
| Messages Applicable to TST001, TST101, KST101 and K10CR1 | 56 |
| Messages Applicable to TST101 and KST101 | 4 |
| Messages Applicable to TST001 | 3 |
| Messages Applicable to KST101 Only | 6 |
| Messages Applicable to KST201 Only | 49 |
| Messages Applicable to K10CR1 Only | 0 |
| Messages Applicable to BSC10x and BSC20x | 69 |
| Messages Applicable to LTS Series of Devices | 46 |
| Messages Applicable to MLJ050, MLJ150 and MLJ250 | 47 |
| Messages Applicable to MFF101 and MFF102 | 12 |
| Messages Applicable to BBD10x, BBD20x, BBD30x, KBD101 | 87 |
| Messages Applicable to KBD101 and KVC101 Only | 5 |
| Messages Applicable to KVC101 Only | 71 |
| Messages Applicable to BBD30x and KVC101 | 6 |
| Messages Applicable to PDXC2 and PDXC3 | 26 |
| Messages Applicable to BBD301, BBD302 and BBD303 Only | 21 |
| Messages Applicable to BNT001, MNA601, TNA001 and KNA101 | 58 |
| Messages Applicable to KNA101 Only | 14 |
| Messages Applicable to TLS001, KLS635 and KLS1550 | 15 |
| Messages Applicable Only to KLS635 and KLS1550 | 2 |
| Messages Applicable to TLD001 and KLD101 | 24 |
| Messages Applicable Only to KLD101 | 2 |
| Messages Applicable to TQD001, TPA101 and KPA101 | 12 |
| Messages Applicable to TPA101 and KPA101 Only | 1 |
| Messages Applicable to KPA101 Only | 0 |
| Messages Applicable to TTC001 | 12 |
| Messages Applicable to TIM101, KIM001 and KIM101 | 23 |
| Messages Applicable to MPC220 and MPC320 | 22 |
| Messages Applicable to CT1P | 49 |
| Messages Applicable to GNMx Series of Devices | 53 |
| Messages Applicable to UMC1, UMC2 and UMC3 | 82 |

## Supplied header inventory

Each header below was inventoried for its declarations. This is a checklist of the source scope, **not a declaration that every exported function has been implemented**. Consult the typed table above and the command catalog for actual coverage. In particular, Joystick and TDIEngine are not implemented as dedicated APIs.

- `ThorLabs.MotionControl.FilterFlipper.h`
- `ThorLabs.MotionControl.ModularRack.h`
- `Thorlabs.MotionControl.Benchtop.BrushlessMotor.h`
- `Thorlabs.MotionControl.Benchtop.DCServo.h`
- `Thorlabs.MotionControl.Benchtop.NanoTrak.h`
- `Thorlabs.MotionControl.Benchtop.Piezo.PDXC2.h`
- `Thorlabs.MotionControl.Benchtop.Piezo.UDXC.h`
- `Thorlabs.MotionControl.Benchtop.Piezo.h`
- `Thorlabs.MotionControl.Benchtop.PrecisionPiezo.h`
- `Thorlabs.MotionControl.Benchtop.StepperMotor.h`
- `Thorlabs.MotionControl.IntegratedPrecisionPiezo.h`
- `Thorlabs.MotionControl.IntegratedStepperMotors.h`
- `Thorlabs.MotionControl.KCube.BrushlessMotor.h`
- `Thorlabs.MotionControl.KCube.DCServo.h`
- `Thorlabs.MotionControl.KCube.InertialMotor.h`
- `Thorlabs.MotionControl.KCube.LaserDiode.h`
- `Thorlabs.MotionControl.KCube.LaserSource.h`
- `Thorlabs.MotionControl.KCube.LiquidCrystal.h`
- `Thorlabs.MotionControl.KCube.NanoTrak.h`
- `Thorlabs.MotionControl.KCube.Piezo.h`
- `Thorlabs.MotionControl.KCube.PiezoStrainGauge.h`
- `Thorlabs.MotionControl.KCube.PositionAligner.h`
- `Thorlabs.MotionControl.KCube.Solenoid.h`
- `Thorlabs.MotionControl.KCube.StepperMotor.h`
- `Thorlabs.MotionControl.KCube.StrainGauge.h`
- `Thorlabs.MotionControl.KCubeEthernetHub.h`
- `Thorlabs.MotionControl.ModularRack.BrushlessMotor.h`
- `Thorlabs.MotionControl.ModularRack.NanoTrak.h`
- `Thorlabs.MotionControl.ModularRack.Piezo.h`
- `Thorlabs.MotionControl.ModularRack.StepperMotor.h`
- `Thorlabs.MotionControl.Polarizer.h`
- `Thorlabs.MotionControl.PositionReadoutEncoder.h`
- `Thorlabs.MotionControl.TCube.BrushlessMotor.h`
- `Thorlabs.MotionControl.TCube.DCServo.h`
- `Thorlabs.MotionControl.TCube.InertialMotor.h`
- `Thorlabs.MotionControl.TCube.LaserDiode.h`
- `Thorlabs.MotionControl.TCube.LaserSource.h`
- `Thorlabs.MotionControl.TCube.NanoTrak.h`
- `Thorlabs.MotionControl.TCube.Piezo.h`
- `Thorlabs.MotionControl.TCube.Quad.h`
- `Thorlabs.MotionControl.TCube.Solenoid.h`
- `Thorlabs.MotionControl.TCube.StepperMotor.h`
- `Thorlabs.MotionControl.TCube.StrainGauge.h`
- `Thorlabs.MotionControl.TCube.TEC.h`
- `Thorlabs.MotionControl.TDIEngine.h`
- `Thorlabs.MotionControl.VerticalStage.h`

## Validation boundary

Tests validate packet encoding/decoding, asyncio behavior and Linux serial transport through a pseudo-terminal. They do not validate physical motion, optical outputs, firmware revisions, USB driver binding, native hub networking, or operating limits of attached stages. Before declaring any model fully supported, capture and compare representative hardware transactions, exercise errors and disconnects, confirm its scale/settings, and cover its remaining API surface.
