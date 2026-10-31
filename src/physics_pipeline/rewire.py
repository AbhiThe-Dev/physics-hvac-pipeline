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


# --- Zone-level packaged terminal units (PTAC/PTHP): no AirLoopHVAC branch
# to manipulate at all, so this is a structurally different mechanism from
# everything above, not a special case of it. Verified empirically on
# baseline_sys01 (PTAC) rather than assumed to work like the airloop case:
#   - `unit.remove()` cascade-deletes the WHOLE assembly cleanly in one call
#     (unit + both embedded coils + fan + DX performance curves, confirmed
#     9 objects removed for one PTAC unit) -- no orphaned coil, no need for
#     a `_disconnect_hydronic_reheat_coil`-style pre-step the way an
#     AirLoopHVAC branch removal needs. The plant loop's demand branch for
#     the embedded hydronic coil is removed as part of the same cascade
#     (confirmed: demand component count dropped correctly).
#   - `unit.clone(model)` ALREADY re-plumbs the cloned embedded hydronic
#     coil onto the same plant loop automatically (confirmed:
#     `clonedCoil.plantLoop().is_initialized()` is True immediately after
#     cloning, before `addToThermalZone` is even called) -- unlike
#     VAV:Reheat's clone, which orphans the coil and needs
#     `_reconnect_cloned_hydronic_reheat_coil`'s manual fix-up. No
#     equivalent fix-up is needed or possible here; there is nothing to
#     reconnect.
#   - Forward-translation was clean (0 errors) after both a remove and a
#     clone+addToThermalZone, confirmed directly, not inferred.
_PACKAGED_UNIT_CAST_METHODS: tuple[str, ...] = (
    "to_ZoneHVACPackagedTerminalAirConditioner",
    "to_ZoneHVACPackagedTerminalHeatPump",
)
_PACKAGED_UNIT_GETTERS: tuple[str, ...] = (
    "getZoneHVACPackagedTerminalAirConditioners",
    "getZoneHVACPackagedTerminalHeatPumps",
)


def find_packaged_unit_for_zone(model: "openstudio.model.Model", zone: "openstudio.model.ThermalZone"):
    """Returns the PTAC/PTHP-style unit serving `zone` directly (no
    AirLoopHVAC involved at all), or None if `zone` has no such unit --
    e.g. because it's airloop-served instead, or has no HVAC at all."""
    for equip in zone.equipment():
        for cast_name in _PACKAGED_UNIT_CAST_METHODS:
            opt = getattr(equip, cast_name)()
            if opt.is_initialized():
                return opt.get().to_HVACComponent().get()
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


_SINGLE_ZONE_SETPOINT_MANAGER_CAST_METHODS: tuple[str, ...] = (
    "to_SetpointManagerSingleZoneReheat", "to_SetpointManagerSingleZoneHeating",
    "to_SetpointManagerSingleZoneCooling", "to_SetpointManagerSingleZoneHumidityMinimum",
    "to_SetpointManagerSingleZoneHumidityMaximum", "to_SetpointManagerSingleZoneOneStageCooling",
    "to_SetpointManagerSingleZoneOneStageHeating",
)


def _find_single_zone_setpoint_manager_for(airloop, zone: "openstudio.model.ThermalZone"):
    """A single-zone-per-airloop system (sys03/04/09/10 -- confirmed via
    direct inspection, not assumed to generalize from sys05-08's shared-AHU
    topology) has a `SetpointManager:SingleZone:*` on the AHU's supply
    outlet node whose `controlZone` is that one dedicated zone. Every
    `SetpointManagerSingleZone*` subtype exposes `controlZone()`
    identically, so this isn't specific to `SingleZoneReheat`."""
    for spm in airloop.supplyOutletNode().setpointManagers():
        for cast_name in _SINGLE_ZONE_SETPOINT_MANAGER_CAST_METHODS:
            opt = getattr(spm, cast_name)()
            if opt.is_initialized():
                control_zone = opt.get().controlZone()
                if control_zone.is_initialized() and control_zone.get().handle() == zone.handle():
                    return spm
                break
    return None


def _retarget_single_zone_setpoint_manager(spm, new_zone: "openstudio.model.ThermalZone") -> None:
    """When an airloop SURVIVES a branch swap (its old zone is replaced by
    a new one, not just removed), its `SetpointManager:SingleZone:*` has to
    be repointed at the new zone, not deleted -- found the hard way:
    deleting it (the first fix attempted here) left OTHER setpoint
    managers on the same airloop (e.g. `SetpointManager:MixedAir`, which
    references the SingleZone manager's controlled node as ITS OWN
    setpoint source) with a "missing reference temperature setpoint"
    Fatal error, confirmed by actually simulating, not just translating.
    `setControlZone()` alone (no separate node-field setters exist on this
    class) is enough -- confirmed empirically that it re-derives the
    zone's inlet/exhaust node references, not just the zone name.

    `spm` must be looked up by the caller BEFORE the old zone's branch is
    removed, not after -- `removeBranchForZone` itself resets the setpoint
    manager's `controlZone` to uninitialized as a side effect of removing
    that zone, so a post-removal lookup by "whose control zone is the old
    zone" always comes back empty (same bug found and fixed in
    `_reconcile_single_zone_setpoint_manager_after_removal`, which is why
    both take an already-found `spm` rather than looking it up
    themselves)."""
    if spm is None:
        return
    for cast_name in _SINGLE_ZONE_SETPOINT_MANAGER_CAST_METHODS:
        opt = getattr(spm, cast_name)()
        if opt.is_initialized():
            opt.get().setControlZone(new_zone)
            return


def _reconcile_single_zone_setpoint_manager_after_removal(airloop, spm) -> None:
    """Found on sys03: a `set_ahu_direct_service` fabrication/misattribution
    can leave a single-zone-designed airloop temporarily serving TWO zones
    (its own native one plus a fabricated extra one, via `addBranchForZone`
    onto an already-served AHU -- a legitimate corruption representation,
    same pattern as `add_extra_service`'s donor airloop). If a LATER event
    in the same blueprint then removes the airloop's ORIGINAL (setpoint-
    manager-controlled) zone while the OTHER zone remains, the airloop is
    NOT zone-less afterward (so `_delete_airloop_if_now_zoneless` correctly
    leaves it alone), but its `SetpointManager:SingleZone:*` is now
    pointing at a zone that's no longer on this airloop at all -- a Fatal
    'missing required property' error, confirmed by simulating a real
    two-event blueprint drawn from actual production seeds (severity 2,
    not just an exploratory high-severity sweep).

    `spm` must be looked up by the caller BEFORE `removeBranchForZone` runs,
    not after -- found the hard way: `removeBranchForZone` itself resets
    the setpoint manager's `controlZone` to uninitialized as a side effect
    of removing that zone, so looking it up afterward by "whose control
    zone equals the zone I just removed" always comes back empty, silently
    skipping the retarget this function exists to do. Retargets `spm` to
    whichever zone the airloop still has, if any; a no-op if `spm` is None
    (no single-zone setpoint manager existed for the removed zone) or the
    airloop now has zero zones left (the caller handles that case)."""
    if spm is None:
        return
    remaining = airloop.thermalZones()
    if not remaining:
        return
    for cast_name in _SINGLE_ZONE_SETPOINT_MANAGER_CAST_METHODS:
        opt = getattr(spm, cast_name)()
        if opt.is_initialized():
            opt.get().setControlZone(remaining[0])
            return


def _reconcile_airloop_after_zone_departure(airloop, spm) -> None:
    """Unifies the two possible outcomes once a zone has left `airloop` by
    ANY mechanism -- `removeBranchForZone` (used by `_remove_branch_
    safely`) and `addBranchForZone`'s own auto-move (used by
    `set_ahu_direct_service`) were BOTH found to invalidate a
    `SetpointManager:SingleZone:*`'s control zone as a side effect, the
    same underlying problem reached two different ways. If no zones remain
    on `airloop`, delete it outright (a zone-less single-zone-designed
    airloop is not valid EnergyPlus input). If others remain, retarget the
    setpoint manager to one of them instead of leaving it dangling -- the
    gap that `_remove_branch_safely`'s callers didn't have (it already
    does this internally) but `set_ahu_direct_service`'s `original_airloop`
    handling did, found via a real Fatal error on a genuine production-
    scope seed (severity 3, not just an exploratory high-severity one)."""
    remaining = airloop.thermalZones()
    if not remaining:
        airloop.remove()
        return
    _retarget_single_zone_setpoint_manager(spm, remaining[0])


def _remove_branch_safely(airloop, zone: "openstudio.model.ThermalZone", model: "openstudio.model.Model") -> bool:
    original = find_terminal_for_zone(model, zone)
    if original is not None:
        _disconnect_hydronic_reheat_coil(original)
    spm = _find_single_zone_setpoint_manager_for(airloop, zone)
    if not airloop.removeBranchForZone(zone):
        return False
    _reconcile_single_zone_setpoint_manager_after_removal(airloop, spm)
    return True


def _delete_airloop_if_now_zoneless(airloop) -> None:
    """A dedicated single-zone AirLoopHVAC (sys03/04/09/10 -- confirmed via
    direct inspection: one AirLoopHVAC per zone, not one shared AHU) left
    with zero zones after a branch removal is NOT valid EnergyPlus input on
    its own -- found by actually simulating a rewired model, not just
    forward-translating it (translation stayed clean): "An outlet node in
    AirLoopHVAC=... is not connected to any zone" is a Fatal error at
    input-processing time. Call this only where the caller is NOT about to
    add a fresh branch back onto this SAME airloop object in the same
    operation (that would destroy a reference the caller still needs,
    reproducing the exact stale-reference-after-destroy shape found for
    VAV-terminal branch removal originally) -- i.e. after clearing a
    donor/target zone's OWN prior service where a *different* airloop
    takes over, never after the removal step inside `reassign_terminal`
    that immediately re-adds a branch to `from_airloop` itself. On sys05-08
    (multiple zones per shared AHU) this is always a safe no-op, since
    removing one zone never leaves the AHU with zero remaining zones."""
    if len(airloop.thermalZones()) == 0:
        airloop.remove()


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
    terminal to move.

    Dispatches to the packaged-unit mechanism when `from_zone` has no
    AirLoopHVAC (see `find_packaged_unit_for_zone`) -- within one building
    every zone is served the same way (confirmed: baseline_sys01 has zero
    AirLoopHVACs at all), so cross-architecture donor/target mixing never
    actually occurs here, but `to_zone`'s existing service is removed
    through whichever mechanism actually serves it, not assumed to match
    `from_zone`'s."""
    from_airloop = find_airloop_for_zone(model, from_zone)
    if from_airloop is not None:
        to_airloop = find_airloop_for_zone(model, to_zone)
        _original, clone = clone_terminal_for_zone(model, from_zone)
        if clone is None:
            return False
        # Captured BEFORE the branch removal below -- removeBranchForZone
        # resets this setpoint manager's controlZone as a side effect, so
        # looking it up afterward by "whose control zone is from_zone"
        # would always come back empty.
        from_airloop_spm = _find_single_zone_setpoint_manager_for(from_airloop, from_zone)
        if not _remove_branch_safely(from_airloop, from_zone, model):
            return False
        if to_airloop is not None:
            if not _remove_branch_safely(to_airloop, to_zone, model):
                return False
            # to_airloop gets nothing added back to it in this operation
            # (its zone is moving to from_airloop instead) -- unlike
            # from_airloop, which is used again on the next line, so it's
            # safe to delete here if that emptied it. EXCEPT when
            # to_airloop IS from_airloop (found via a real crash: an
            # earlier event in the same blueprint can fabricate a second
            # zone onto an airloop, so from_zone and to_zone can end up on
            # the SAME airloop here -- deleting it out from under the
            # `from_airloop.addBranchForZone` call two lines down segfaults
            # on the now-destroyed reference, the exact stale-object shape
            # this pipeline has been careful about from the start).
            if to_airloop.handle() != from_airloop.handle():
                _delete_airloop_if_now_zoneless(to_airloop)
        if not from_airloop.addBranchForZone(to_zone, clone):
            return False
        # from_airloop survives with a DIFFERENT zone now -- retarget its
        # single-zone setpoint manager rather than leaving it pointing at
        # from_zone (a no-op on sys05-08, which use different setpoint
        # manager types entirely).
        _retarget_single_zone_setpoint_manager(from_airloop_spm, to_zone)
        return True

    from_unit = find_packaged_unit_for_zone(model, from_zone)
    if from_unit is None:
        return False
    clone = from_unit.clone(model).to_HVACComponent().get()
    if not _remove_packaged_unit_safely(model, from_zone):
        return False
    if not _remove_packaged_unit_safely(model, to_zone):
        return False
    return clone.to_ZoneHVACComponent().get().addToThermalZone(to_zone)


def _remove_packaged_unit_safely(model: "openstudio.model.Model", zone: "openstudio.model.ThermalZone") -> bool:
    """Removes whatever packaged unit currently serves `zone`, if any --
    a no-op returning True if `zone` has none (mirroring `_remove_branch_
    safely`'s pattern of "only attempts removal if there's something to
    remove"), so callers can call this unconditionally on a target zone
    that might or might not already have service."""
    unit = find_packaged_unit_for_zone(model, zone)
    if unit is None:
        return True
    return len(unit.remove()) > 0


def remove_zone_service(model: "openstudio.model.Model", zone: "openstudio.model.ThermalZone") -> bool:
    """Physically disconnects `zone` from its air loop entirely (a removal
    corruption's blueprint claims no connection exists). Dispatches to the
    packaged-unit mechanism (a full cascade-delete via `.remove()`,
    confirmed empirically to cleanly remove the unit, both embedded coils,
    and the fan in one call, with no orphaned plant-loop branch left
    behind) when `zone` has no AirLoopHVAC. Also deletes the whole airloop,
    not just the branch, if `zone` was the airloop's only one (see
    `_delete_airloop_if_now_zoneless`) -- nothing gets added back here, so
    a zone-less airloop left behind would be a permanently invalid,
    orphaned object, not a transient state."""
    airloop = find_airloop_for_zone(model, zone)
    if airloop is not None:
        if not _remove_branch_safely(airloop, zone, model):
            return False
        _delete_airloop_if_now_zoneless(airloop)
        return True
    unit = find_packaged_unit_for_zone(model, zone)
    if unit is None:
        return False
    return len(unit.remove()) > 0


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
    just because there was nothing to remove.

    On a single-zone-per-airloop building (sys03/04/09/10 -- exercised for
    the first time here, since sys05-08 have only one AHU total, so `zone`
    and `airloop` were always already the same pairing and this branch
    never mattered), `addBranchForZone` was found to silently auto-move
    `zone`'s existing connection away from whatever airloop it was
    genuinely on -- confirmed by direct before/after inspection, not
    assumed -- leaving that OTHER airloop's `SetpointManager:SingleZone:*`
    dangling, the same Fatal-at-simulation-time shape found for
    `reassign_terminal`. `zone`'s original airloop (and its setpoint
    manager, captured BEFORE the move -- `addBranchForZone` resets it as a
    side effect the same way `removeBranchForZone` does) is reconciled
    afterward via `_reconcile_airloop_after_zone_departure`: deleted if the
    move left it with zero zones, or retargeted to a remaining zone if a
    PRIOR event in the same blueprint had already added an extra one to it
    (found on a genuine production-scope seed, not just an exploratory
    one -- an earlier fabrication event can leave an airloop temporarily
    serving two zones, and this move can then vacate only one of them)."""
    original_airloop = find_airloop_for_zone(model, zone)
    original_spm = _find_single_zone_setpoint_manager_for(original_airloop, zone) if original_airloop is not None else None
    if zone.handle() in {z.handle() for z in airloop.thermalZones()}:
        if not _remove_branch_safely(airloop, zone, model):
            return False
    passthrough = openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
        model, model.alwaysOnDiscreteSchedule()
    )
    ok = airloop.addBranchForZone(zone, passthrough.to_HVACComponent().get())
    if ok and original_airloop is not None and original_airloop.handle() != airloop.handle():
        _reconcile_airloop_after_zone_departure(original_airloop, original_spm)
    return ok


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
    branch on top of an already-served zone.

    Dispatches to the packaged-unit mechanism when `donor_zone` has no
    AirLoopHVAC -- same reasoning and same empirical basis as
    `reassign_terminal`."""
    donor_airloop = find_airloop_for_zone(model, donor_zone)
    if donor_airloop is not None:
        target_airloop = find_airloop_for_zone(model, target_zone)
        _original, clone = clone_terminal_for_zone(model, donor_zone)
        if clone is None:
            return False
        if target_airloop is not None:
            if not _remove_branch_safely(target_airloop, target_zone, model):
                return False
            # target_airloop gets nothing added back (the clone goes onto
            # donor_airloop instead), so it's safe -- and necessary -- to
            # delete it here if that emptied it. EXCEPT when target_airloop
            # IS donor_airloop (same aliasing risk found and fixed in
            # reassign_terminal: an earlier event can fabricate donor_zone
            # and target_zone onto the same airloop) -- donor_airloop.
            # addBranchForZone two lines down needs it to still exist.
            if target_airloop.handle() != donor_airloop.handle():
                _delete_airloop_if_now_zoneless(target_airloop)
        return donor_airloop.addBranchForZone(target_zone, clone)

    donor_unit = find_packaged_unit_for_zone(model, donor_zone)
    if donor_unit is None:
        return False
    clone = donor_unit.clone(model).to_HVACComponent().get()
    if not _remove_packaged_unit_safely(model, target_zone):
        return False
    return clone.to_ZoneHVACComponent().get().addToThermalZone(target_zone)


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


def _find_owning_packaged_unit(model: "openstudio.model.Model", coil):
    """A PTAC's heating coil isn't a standalone AHU-level coil
    (`removeFromAirLoopHVAC()` returns False, it isn't on any air loop at
    all) and isn't embedded in a VAV:Reheat terminal either -- a third,
    structurally different case `remove_coil_service`'s original two
    branches don't cover, found by auditing this exact function against
    baseline_sys01 rather than assuming the VAV:Reheat branch would somehow
    also catch it."""
    for getter_name in _PACKAGED_UNIT_GETTERS:
        for unit in getattr(model, getter_name)():
            heating_coil = unit.heatingCoil().to_CoilHeatingWater()
            if heating_coil.is_initialized() and heating_coil.get().handle() == coil.handle():
                return unit
    return None


def remove_coil_service(model: "openstudio.model.Model", coil) -> bool:
    """Fully removes `coil` -- disconnects it from its plant loop and its
    air loop, then deletes the now-orphaned object outright. Represents
    "no pump feeds this coil" as a standalone, simulatable configuration,
    the coil-level equivalent of `remove_zone_service`.

    Three structurally different cases, all confirmed empirically rather
    than assumed to work the same way:
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
        possible here, the coil is already gone once the terminal is.
      - A PTAC's heating coil (baseline_sys01): `removeFromAirLoopHVAC()`
        returns False (it isn't on any air loop -- there is none) and
        `_find_owning_reheat_terminal` also finds nothing (it isn't a
        VAV:Reheat terminal either) -- found by auditing this function
        against sys01 rather than assuming the existing two branches
        already covered it. Unlike VAV:Reheat, there is no
        "PTAC:NoReheat" -- `ZoneHVAC:PackagedTerminalAirConditioner`
        requires a heating coil field, so removing it outright isn't a
        valid configuration to construct. `setHeatingCoil()` (confirmed
        present on the OpenStudio API) is used instead to swap in a fresh
        `Coil:Heating:Electric`, then the old hydronic coil -- now
        unreferenced by anything -- is deleted directly: physically "this
        coil's water connection is gone" without deleting fan/cooling/zone
        service, the same minimal-change spirit as the VAV:NoReheat swap,
        just via a coil substitution instead of a coil-less terminal type
        (which doesn't exist for this equipment)."""
    if coil.removeFromAirLoopHVAC():
        coil.removeFromPlantLoop()
        return len(coil.remove()) > 0

    terminal = _find_owning_reheat_terminal(model, coil)
    if terminal is not None:
        zone, airloop = _zone_and_airloop_for_terminal(model, terminal)
        if zone is None:
            return False
        if not _remove_branch_safely(airloop, zone, model):
            return False
        no_reheat = openstudio.model.AirTerminalSingleDuctVAVNoReheat(model, model.alwaysOnDiscreteSchedule())
        return airloop.addBranchForZone(zone, no_reheat.to_HVACComponent().get())

    unit = _find_owning_packaged_unit(model, coil)
    if unit is None:
        return False
    replacement = openstudio.model.CoilHeatingElectric(model, model.alwaysOnDiscreteSchedule())
    if not unit.setHeatingCoil(replacement.to_HVACComponent().get()):
        return False
    return len(coil.remove()) > 0


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
    returns an empty map.

    Extended (not assumed to already cover this) for zone-level packaged
    units: PTAC's heating coil is `Coil:Heating:Water` on a real, shared
    plant loop -- checked directly on baseline_sys01, not inherited from
    sys06's zero-plant-loop proof, since PTAC/PTHP still have coils where
    sys06 effectively didn't. Without this, `remove_zone_service`'s
    `unit.remove()` cascade-deletes that same coil with nothing tracking
    it, reproducing the exact cross-event collision this map exists to
    prevent, just on a different object type. PTHP's coils are both DX
    (confirmed empirically: zero PlantLoops, zero pumps in baseline_sys02
    at all), so PTHP units never add an entry here -- correctly, and for
    its own confirmed reason, not by assuming it behaves like sys06."""
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

    for zone in model.getThermalZones():
        unit = find_packaged_unit_for_zone(model, zone)
        if unit is None:
            continue
        for cast_name in ("to_ZoneHVACPackagedTerminalAirConditioner", "to_ZoneHVACPackagedTerminalHeatPump"):
            opt = getattr(unit, cast_name)()
            if not opt.is_initialized():
                continue
            heating_coil = opt.get().heatingCoil().to_CoilHeatingWater()
            if heating_coil.is_initialized():
                zone_to_coil[str(zone.handle())] = str(heating_coil.get().handle())
    return zone_to_coil
