"""Verify EnergyPlus Operational Fault injection: OpenStudio's Model API has
no wrapper class for FaultModel:* objects (checked: nothing in
dir(openstudio.model) matches "fault", case-insensitive), so faults must be
added as raw IDF objects on the post-translation Workspace.
"""
import openstudio

SRC = "vendor/OpenStudio-resources/model/simulationtests/baseline_sys08.osm"
translator = openstudio.osversion.VersionTranslator()
model = translator.loadModel(openstudio.path(SRC)).get()

rp = model.getRunPeriod()
rp.setBeginMonth(1); rp.setBeginDayOfMonth(1)
rp.setEndMonth(1); rp.setEndDayOfMonth(3)
ov = openstudio.model.OutputVariable("Zone Mean Air Temperature", model)
ov.setReportingFrequency("Hourly")

target_zone_name = "Thermal Zone 7"
tz = [z for z in model.getThermalZones() if z.name().get() == target_zone_name][0]

ft = openstudio.energyplus.ForwardTranslator()
ws = ft.translateModel(model)

thermostat_name = f"{target_zone_name} Thermostat"
found = [o for o in ws.getObjectsByType(openstudio.IddObjectType("ZoneControl:Thermostat"))
         if o.getString(0).get() == thermostat_name]
print("Found ZoneControl:Thermostat objects matching:", len(found))
assert found, f"no ZoneControl:Thermostat named {thermostat_name!r}"

fault_idf = openstudio.IdfObject(openstudio.IddObjectType("FaultModel:ThermostatOffset"))
fault_idf.setString(0, "Fault Thermostat Offset Zone7")   # Name
fault_idf.setString(1, thermostat_name)                    # Thermostat Name
fault_idf.setString(2, "Always_On")                        # Availability Schedule Name
fault_idf.setString(3, "Always_On")                        # Severity Schedule Name
fault_idf.setDouble(4, 5.0)                                # Reference Thermostat Offset (degC)
added = ws.addObject(fault_idf)
print("Fault object added:", added.is_initialized())

ws.save(openstudio.path("vendor/fault_test.idf"), True)
print("Saved vendor/fault_test.idf")
