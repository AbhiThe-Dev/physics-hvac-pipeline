"""Step 0.4: verify a rewired OpenStudio model still runs in EnergyPlus."""
import openstudio
import sys

SRC = "vendor/OpenStudio-resources/model/simulationtests/baseline_sys08.osm"
OUT_OSM = "vendor/rewired_test.osm"
OUT_IDF = "vendor/rewired_test.idf"

translator = openstudio.osversion.VersionTranslator()
model = translator.loadModel(openstudio.path(SRC)).get()
airloop = model.getAirLoopHVACs()[0]

# Shrink to a 3-day run period and add minimal, targeted outputs (not full annual
# sub-hourly on everything) -- this is what Step 0.5's storage/runtime estimate
# will be based on.
rp = model.getRunPeriod()
rp.setBeginMonth(1)
rp.setBeginDayOfMonth(1)
rp.setEndMonth(1)
rp.setEndDayOfMonth(3)

for var_name in ["Zone Mean Air Temperature", "System Node Mass Flow Rate", "System Node Temperature"]:
    ov = openstudio.model.OutputVariable(var_name, model)
    ov.setReportingFrequency("Hourly")

# --- identify two terminal/zone branch pairs ---
demand = airloop.demandComponents()
term_to_zone = {}
i = 0
while i < len(demand):
    c = demand[i]
    if c.iddObjectType().valueName() == "OS_AirTerminal_SingleDuct_ParallelPIU_Reheat":
        j = i + 1
        while j < len(demand) and demand[j].iddObjectType().valueName() != "OS_ThermalZone":
            j += 1
        if j < len(demand):
            term_to_zone[c.handle()] = demand[j].to_ThermalZone().get()
    i += 1

items = list(term_to_zone.items())
termA_h, zoneA = items[0]
termB_h, zoneB = items[1]
termA = model.getAirTerminalSingleDuctParallelPIUReheat(termA_h).get()
termB = model.getAirTerminalSingleDuctParallelPIUReheat(termB_h).get()
print(f"Before rewire: '{termA.name().get()}' -> '{zoneA.name().get()}', "
      f"'{termB.name().get()}' -> '{zoneB.name().get()}'")

# IMPORTANT gotcha found in Step 0.4: airLoopHVAC.removeBranchForZone() destroys
# the terminal object along with the branch (the Python wrapper becomes a stale
# handle -- calling further methods on it segfaults the process rather than
# raising a Python exception). Clone the terminals BEFORE removing branches.
cloneA = termA.clone(model).to_AirTerminalSingleDuctParallelPIUReheat().get()
cloneB = termB.clone(model).to_AirTerminalSingleDuctParallelPIUReheat().get()

ok1 = airloop.removeBranchForZone(zoneA)
ok2 = airloop.removeBranchForZone(zoneB)
print(f"removeBranchForZone: zoneA={ok1}, zoneB={ok2}")

# True swap: zoneA now gets what used to be termB's clone, zoneB gets termA's clone.
ok3 = airloop.addBranchForZone(zoneA, cloneB.to_HVACComponent().get())
ok4 = airloop.addBranchForZone(zoneB, cloneA.to_HVACComponent().get())
print(f"addBranchForZone (swapped): zoneA={ok3}, zoneB={ok4}")

zones_served = sorted(z.name().get() for z in airloop.thermalZones())
print("Zones served after rewire:", zones_served)
assert zoneA.name().get() in zones_served and zoneB.name().get() in zones_served, "rewire broke zone coverage"
assert len(zones_served) == 10, f"expected 10 zones still served, got {len(zones_served)}"

model.save(openstudio.path(OUT_OSM), True)
print(f"Saved rewired OSM: {OUT_OSM}")

ft = openstudio.energyplus.ForwardTranslator()
workspace = ft.translateModel(model)
workspace.save(openstudio.path(OUT_IDF), True)
print(f"Saved forward-translated IDF: {OUT_IDF}")

errs = ft.errors()
warns = ft.warnings()
print(f"Forward translation: {len(errs)} errors, {len(warns)} warnings")
for e in errs:
    print("  ERROR:", e.logMessage())
if errs:
    sys.exit(1)
