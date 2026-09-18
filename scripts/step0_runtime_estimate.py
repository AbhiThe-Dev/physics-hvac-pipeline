"""Step 0.5: runtime/storage estimate at a realistic scoped-output config."""
import argparse
import openstudio

p = argparse.ArgumentParser()
p.add_argument("--days", type=int, default=14)
p.add_argument("--out-osm", default="vendor/estimate_test.osm")
p.add_argument("--out-idf", default="vendor/estimate_test.idf")
args = p.parse_args()

SRC = "vendor/OpenStudio-resources/model/simulationtests/baseline_sys08.osm"
translator = openstudio.osversion.VersionTranslator()
model = translator.loadModel(openstudio.path(SRC)).get()

rp = model.getRunPeriod()
rp.setBeginMonth(1)
rp.setBeginDayOfMonth(1)
if args.days >= 365:
    rp.setEndMonth(12)
    rp.setEndDayOfMonth(31)
else:
    rp.setEndMonth(7)
    rp.setEndDayOfMonth(min(args.days, 31))

# Scoped output: only the variables an AHU/VAV/zone fault-diagnosis signal needs,
# at hourly frequency (not full sub-hourly on everything).
for var_name in [
    "Zone Mean Air Temperature",
    "Zone Air Terminal VAV Damper Position",
    "System Node Mass Flow Rate",
    "System Node Temperature",
    "System Node Setpoint Temperature",
    "Fan Electricity Rate",
    "Cooling Coil Total Cooling Rate",
    "Heating Coil Heating Rate",
    "Zone Thermostat Heating Setpoint Temperature",
    "Zone Thermostat Cooling Setpoint Temperature",
]:
    ov = openstudio.model.OutputVariable(var_name, model)
    ov.setReportingFrequency("Hourly")

model.save(openstudio.path(args.out_osm), True)
ft = openstudio.energyplus.ForwardTranslator()
workspace = ft.translateModel(model)
workspace.save(openstudio.path(args.out_idf), True)
print(f"days={args.days} -> saved {args.out_idf}")
