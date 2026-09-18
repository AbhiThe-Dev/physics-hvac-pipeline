"""Physical model-rewiring primitives, built on two mechanisms verified
empirically in Step 0 / while building this pipeline:

1. `airLoopHVAC.removeBranchForZone()` destroys the terminal object along
   with the branch, so any terminal that must be reused elsewhere has to be
   cloned *before* its branch is removed -- calling a method on the stale
   wrapper afterward segfaults the process rather than raising a catchable
   exception.
2. For a terminal with a water-side reheat coil (e.g. VAV:Reheat on a
   hot-water loop), `removeBranchForZone` does NOT clean up that coil's
   plant-loop connection. The orphaned Coil:Heating:Water forward-translates
   fine but then fails EnergyPlus input processing with a Fatal error
   ("Missing required property 'air_inlet_node_name'", etc.) -- found while
   testing removal corruptions on baseline_sys07 (VAV:Reheat terminals),
   absent on baseline_sys08 (Parallel PIU:Reheat with an electric, not
   hydronic, reheat coil). Every branch removal in this module routes
   through `_remove_branch_safely` so the coil is disconnected first, while
   the terminal object is still valid.
"""

from __future__ import annotations

import openstudio


def find_airloop_for_zone(model: "openstudio.model.Model", zone: "openstudio.model.ThermalZone"):
    for al in model.getAirLoopHVACs():
        if zone.handle() in {z.handle() for z in al.thermalZones()}:
            return al
    return None


def find_terminal_for_zone(model: "openstudio.model.Model", zone: "openstudio.model.ThermalZone"):
    """Returns the terminal unit (as an HVACComponent) currently serving
    `zone` on its air loop, without cloning it."""
    airloop = find_airloop_for_zone(model, zone)
    if airloop is None:
        return None
    demand = airloop.demandComponents()
    i = 0
    while i < len(demand):
        c = demand[i]
        if "AirTerminal" in c.iddObjectType().valueName():
            j = i + 1
            while j < len(demand) and demand[j].iddObjectType().valueName() != "OS_ThermalZone":
                j += 1
            if j < len(demand) and demand[j].to_ThermalZone().get().handle() == zone.handle():
                return c.to_HVACComponent().get()
        i += 1
    return None


def _reconnect_cloned_hydronic_reheat_coil(original, clone) -> None:
    """`.clone()` on a VAV:Reheat terminal deep-copies its reheat coil
    object but does NOT re-plumb the copy onto the original's hot-water
    plant loop -- confirmed empirically: forward-translating a model with
    such a clone fails with "Missing required property 'water_inlet_node_
    name'" (and outlet) on the cloned coil, since it was never added to any
    plant loop's demand side. Find whichever plant loop the original coil
    is on and add the clone's coil to the same loop."""
    orig_vav_reheat = original.to_AirTerminalSingleDuctVAVReheat()
    clone_vav_reheat = clone.to_AirTerminalSingleDuctVAVReheat()
    if not (orig_vav_reheat.is_initialized() and clone_vav_reheat.is_initialized()):
        return
    orig_coil = orig_vav_reheat.get().reheatCoil().to_CoilHeatingWater()
    clone_coil = clone_vav_reheat.get().reheatCoil().to_CoilHeatingWater()
    if not (orig_coil.is_initialized() and clone_coil.is_initialized()):
        return
    plant_loop = orig_coil.get().plantLoop()
    if plant_loop.is_initialized():
        plant_loop.get().addDemandBranchForComponent(clone_coil.get())


def clone_terminal_for_zone(model: "openstudio.model.Model", zone: "openstudio.model.ThermalZone"):
    """Returns the terminal unit (as an HVACComponent) currently serving
    `zone` on its air loop, and a clone of it (the clone is what survives
    once the original's branch is removed)."""
    original = find_terminal_for_zone(model, zone)
    if original is None:
        return None, None
    clone = original.clone(model).to_HVACComponent().get()
    _reconnect_cloned_hydronic_reheat_coil(original, clone)
    return original, clone


def _disconnect_hydronic_reheat_coil(terminal) -> None:
    to_vav_reheat = terminal.to_AirTerminalSingleDuctVAVReheat()
    if to_vav_reheat.is_initialized():
        coil = to_vav_reheat.get().reheatCoil()
        water_coil = coil.to_CoilHeatingWater()
        if water_coil.is_initialized():
            water_coil.get().removeFromPlantLoop()


def _remove_branch_safely(airloop, zone: "openstudio.model.ThermalZone", model: "openstudio.model.Model") -> bool:
    original = find_terminal_for_zone(model, zone)
    if original is not None:
        _disconnect_hydronic_reheat_coil(original)
    return airloop.removeBranchForZone(zone)


def reassign_terminal(
    model: "openstudio.model.Model",
    from_zone: "openstudio.model.ThermalZone",
    to_zone: "openstudio.model.ThermalZone",
) -> bool:
    """Physically moves whichever terminal serves `from_zone` so it instead
    serves `to_zone` (a misattribution-style rewire). `to_zone` already has
    its own (true) terminal -- misattribution only changes who is claimed
    to feed it, the physical zone doesn't go unconditioned -- so that
    existing branch has to be removed first, same as `add_extra_service`.
    Returns False without modifying the model if `from_zone` has no
    terminal to move."""
    from_airloop = find_airloop_for_zone(model, from_zone)
    to_airloop = find_airloop_for_zone(model, to_zone)
    if from_airloop is None:
        return False
    _original, clone = clone_terminal_for_zone(model, from_zone)
    if clone is None:
        return False
    if not _remove_branch_safely(from_airloop, from_zone, model):
        return False
    if to_airloop is not None:
        if not _remove_branch_safely(to_airloop, to_zone, model):
            return False
    return from_airloop.addBranchForZone(to_zone, clone)


def remove_zone_service(model: "openstudio.model.Model", zone: "openstudio.model.ThermalZone") -> bool:
    """Physically disconnects `zone` from its air loop entirely (a removal
    corruption's blueprint claims no connection exists)."""
    airloop = find_airloop_for_zone(model, zone)
    if airloop is None:
        return False
    return _remove_branch_safely(airloop, zone, model)


def set_ahu_direct_service(
    model: "openstudio.model.Model",
    airloop: "openstudio.model.AirLoopHVAC",
    zone: "openstudio.model.ThermalZone",
) -> bool:
    """Physically realizes "the AHU feeds `zone` directly, bypassing any
    terminal unit" -- an AHU-direct corruption's blueprint claims this
    (fabrication), or claims it as the wrong parent in place of the true
    terminal (misattribution).

    Verified in Step 0: `AirLoopHVAC.addBranchForZone(zone)` -- the
    single-argument, no-terminal overload -- does NOT produce a bare
    connection on an airloop that already has terminal-served zones; it
    silently auto-clones a matching terminal instead (confirmed with three
    call variants, including an explicit empty `OptionalStraightComponent`).
    The actual "AHU serves this zone directly" configuration is a minimal
    `AirTerminalSingleDuctConstantVolumeNoReheat` -- no coil, no independent
    flow modulation, a bare duct pass-through -- added via the explicit
    3-argument overload. Whatever currently serves `zone` is removed first,
    through the same `_remove_branch_safely` helper every other rewire here
    uses (handles the hydronic-coil lifetime issue generically; the fresh
    pass-through terminal constructed here is a new object, never a stale
    reference to something just destroyed, so the segfault-causing pattern
    from `removeBranchForZone` doesn't apply to the construction side).
    Mirrors `add_extra_service`'s guard: only attempts removal if `zone`
    is already served by this airloop, so an unserved zone isn't rejected
    just because there was nothing to remove."""
    if zone.handle() in {z.handle() for z in airloop.thermalZones()}:
        if not _remove_branch_safely(airloop, zone, model):
            return False
    passthrough = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
        model, model.alwaysOnDiscreteSchedule()
    )
    return airloop.addBranchForZone(zone, passthrough.to_HVACComponent().get())


def add_extra_service(
    model: "openstudio.model.Model",
    donor_zone: "openstudio.model.ThermalZone",
    target_zone: "openstudio.model.ThermalZone",
) -> bool:
    """Physically realizes "the donor's terminal type feeds target_zone" (a
    fabrication corruption's blueprint claims a connection that was never
    built). `AirLoopHVAC.addBranchForZone` refuses a second branch to a zone
    that already has one (confirmed empirically -- every zone in these test
    buildings is already served), so this is the same physical operation as
    `reassign_terminal`: replace whatever currently serves `target_zone`
    with a clone of the donor's terminal, rather than layer a redundant
    branch on top of an already-served zone."""
    donor_airloop = find_airloop_for_zone(model, donor_zone)
    target_airloop = find_airloop_for_zone(model, target_zone)
    if donor_airloop is None:
        return False
    _original, clone = clone_terminal_for_zone(model, donor_zone)
    if clone is None:
        return False
    if target_airloop is not None:
        if not _remove_branch_safely(target_airloop, target_zone, model):
            return False
    return donor_airloop.addBranchForZone(target_zone, clone)


# --- Pump/coil primitives ---
#
# Structurally different from the terminal<->zone case, confirmed in Step 0
# rather than assumed: `coil.removeFromPlantLoop()` does NOT destroy the
# coil object (unlike `removeBranchForZone` destroying a terminal) -- the
# same Python reference stays valid and can be reconnected elsewhere
# directly, no cloning needed. Two different disconnect APIs
# (`coil.removeFromPlantLoop()` and `plantLoop.removeDemandBranchWithComponent
# (coil)`) were verified to behave identically.
#
# A coil left on the air side with no water connection is NOT valid
# EnergyPlus input (fails translation-to-simulation with a missing-node-
# name error) -- unlike a zone, which can validly go unconditioned. A
# genuine "no pump feeds this coil" removal therefore has to delete the
# coil from both the plant AND air side, not just disconnect the water
# side, or it's left an orphan.
#
# Reassigning a coil to a *different* plant loop (fabrication and
# misattribution are the same physical operation here, same as they turned
# out to be for terminal<->zone) can produce a functioning EnergyPlus model
# that still shows severe errors -- e.g. moving a cooling coil onto a hot-
# water loop causes a `FindRootSimpleController` convergence failure, not
# a translation error. That's the physical-plausibility check correctly
# reporting "this claimed configuration doesn't actually work," not a bug
# in the rewire call. It happens on both current test buildings because
# each has only one pump per water medium, so there's no alternate same-
# medium pump to misattribute to.


def _find_owning_reheat_terminal(model: "openstudio.model.Model", coil):
    """A coil target isn't always a standalone AHU-level coil directly on
    a supply branch (sys08's central cooling coil) -- confirmed on sys07,
    most Heating_Coil candidates are reheat coils *embedded inside* a
    VAV:Reheat terminal, which `coil.removeFromAirLoopHVAC()` doesn't
    reach at all (it only knows about direct branch components, so it
    just returns False -- silently, not an exception, easy to miss)."""
    for terminal in model.getAirTerminalSingleDuctVAVReheats():
        reheat_coil = terminal.reheatCoil().to_CoilHeatingWater()
        if reheat_coil.is_initialized() and reheat_coil.get().handle() == coil.handle():
            return terminal
    return None


def _zone_and_airloop_for_terminal(model: "openstudio.model.Model", terminal):
    handle = terminal.handle()
    for airloop in model.getAirLoopHVACs():
        demand = airloop.demandComponents()
        for i, c in enumerate(demand):
            if c.handle() == handle:
                j = i + 1
                while j < len(demand) and demand[j].iddObjectType().valueName() != "OS_ThermalZone":
                    j += 1
                if j < len(demand):
                    return demand[j].to_ThermalZone().get(), airloop
    return None, None


def remove_coil_service(model: "openstudio.model.Model", coil) -> bool:
    """Fully removes `coil` -- disconnects it from its plant loop and its
    air loop, then deletes the now-orphaned object outright. Represents
    "no pump feeds this coil" as a standalone, simulatable configuration,
    the coil-level equivalent of `remove_zone_service`.

    Two structurally different cases, both confirmed empirically rather
    than assumed:
      - A standalone AHU-level coil directly on a supply branch (e.g.
        sys08's central cooling coil): `removeFromAirLoopHVAC()` +
        `removeFromPlantLoop()` + `.remove()` deletes it cleanly.
      - A reheat coil embedded inside a VAV:Reheat terminal (most
        Heating_Coil targets on sys07): `removeFromAirLoopHVAC()` returns
        False (it isn't a direct branch component), and simply calling
        `.remove()` on the coil directly does nothing useful either -- the
        coil has to go by removing the *terminal* that owns it, via the
        same `_remove_branch_safely` every other rewire here uses (which
        already disconnects a hydronic reheat coil's plant connection
        before the terminal is destroyed), then rebuilding that zone's
        service with a no-reheat VAV terminal (same box, same airflow
        behavior, just without the coil) so the zone stays served.
        Destroying the terminal this way was independently confirmed to
        cascade-delete its reheat coil (found via a cross-event
        interaction while validating this pipeline: an earlier event's
        terminal removal made a *different* event's coil target
        unresolvable) -- no separate coil.remove() call is needed or
        possible here, the coil is already gone once the terminal is."""
    if coil.removeFromAirLoopHVAC():
        coil.removeFromPlantLoop()
        return len(coil.remove()) > 0

    terminal = _find_owning_reheat_terminal(model, coil)
    if terminal is None:
        return False
    zone, airloop = _zone_and_airloop_for_terminal(model, terminal)
    if zone is None:
        return False
    if not _remove_branch_safely(airloop, zone, model):
        return False
    no_reheat = openstudio.model.AirTerminalSingleDuctVAVNoReheat(model, model.alwaysOnDiscreteSchedule())
    return airloop.addBranchForZone(zone, no_reheat.to_HVACComponent().get())


def reassign_coil(model: "openstudio.model.Model", coil, new_pump) -> bool:
    """Physically moves `coil`'s plant-loop connection from wherever it
    currently is to `new_pump`'s plant loop -- the shared physical
    operation behind both a fabrication claim ("this pump feeds this
    coil", when some other pump truly does) and a misattribution claim
    (the true pump swapped for a wrong one), since a coil's water side can
    only ever be on one plant loop at a time, same as
    `reassign_terminal`/`add_extra_service` collapsing to the same
    operation for zone targets. No cloning needed -- `coil` is the same
    object before and after, confirmed to survive disconnection in Step 0."""
    target_loop = new_pump.plantLoop()
    if not target_loop.is_initialized():
        return False
    coil.removeFromPlantLoop()
    return target_loop.get().addDemandBranchForComponent(coil)


def build_zone_to_coil_map(model: "openstudio.model.Model") -> dict[str, str]:
    """Maps each zone (by handle string) to the handle string of its
    terminal's embedded hydronic reheat coil, if any -- the physical fact
    that isn't represented anywhere in the extracted graph (no hasPart
    edge links a Terminal_Unit to its embedded coil there), which is
    exactly why `generate_blueprint`'s `used_targets` guard can't see the
    collision this map exists to catch: destroying a zone's terminal
    (any zone-targeting fabrication/misattribution/removal) cascade-
    deletes this same coil, confirmed empirically while validating the
    pump/coil addition. Only VAV:Reheat terminals have a plant-connected
    (hydronic) coil here -- Parallel PIU:Reheat terminals use an electric
    reheat coil with no plant connection, so `baseline_sys08` always
    returns an empty map."""
    zone_to_coil: dict[str, str] = {}
    for airloop in model.getAirLoopHVACs():
        demand = airloop.demandComponents()
        i = 0
        while i < len(demand):
            c = demand[i]
            if c.iddObjectType().valueName() == "OS_AirTerminal_SingleDuct_VAV_Reheat":
                coil_opt = c.to_AirTerminalSingleDuctVAVReheat().get().reheatCoil().to_CoilHeatingWater()
                if coil_opt.is_initialized():
                    j = i + 1
                    while j < len(demand) and demand[j].iddObjectType().valueName() != "OS_ThermalZone":
                        j += 1
                    if j < len(demand):
                        zone = demand[j].to_ThermalZone().get()
                        zone_to_coil[str(zone.handle())] = str(coil_opt.get().handle())
            i += 1
    return zone_to_coil
