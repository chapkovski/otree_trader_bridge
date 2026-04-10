def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return bool(value)


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def soft_group_matching_enabled(session_config):
    return _as_bool((session_config or {}).get("soft_group_matching_enabled", False), False)


def preferred_players_per_group(session_config, default):
    cfg = session_config or {}
    return max(
        1,
        _as_int(
            cfg.get("preferred_players_per_group", cfg.get("players_per_group", default)),
            default,
        ),
    )


def build_sequential_group_matrix(players, target_group_size):
    ordered_players = sorted(
        list(players or []),
        key=lambda player: _as_int(getattr(player, "id_in_subsession", 0), 0),
    )
    if not ordered_players:
        return []
    group_size = max(1, _as_int(target_group_size, len(ordered_players)))
    return [ordered_players[idx : idx + group_size] for idx in range(0, len(ordered_players), group_size)]


def build_soft_group_matrix(players, target_group_size, planned_participant_count=None):
    ordered_players = sorted(
        list(players or []),
        key=lambda player: _as_int(getattr(player, "id_in_subsession", 0), 0),
    )
    if not ordered_players:
        return []

    group_size = max(1, _as_int(target_group_size, len(ordered_players)))
    actual_total = len(ordered_players)
    planned_total = max(1, _as_int(planned_participant_count, actual_total))
    if planned_total != actual_total:
        planned_total = actual_total

    full_groups = planned_total // group_size
    remainder = planned_total % group_size
    group_sizes = [group_size] * full_groups
    if remainder:
        group_sizes.append(remainder)
    if not group_sizes:
        group_sizes = [actual_total]

    matrix = []
    start = 0
    for size in group_sizes:
        matrix.append(ordered_players[start : start + size])
        start += size
    return [group for group in matrix if group]


def group_matrix_from_participant_match_id(players, var_name="intro_group_match_id"):
    grouped = {}
    for player in sorted(list(players or []), key=lambda p: _as_int(getattr(p, "id_in_subsession", 0), 0)):
        participant = getattr(player, "participant", None)
        participant_vars = getattr(participant, "vars", {}) or {}
        match_id = participant_vars.get(var_name)
        if match_id in (None, ""):
            return []
        grouped.setdefault(_as_int(match_id, 0), []).append(player)
    return [grouped[key] for key in sorted(grouped) if grouped.get(key)]


def session_planned_participant_count(session, fallback=0):
    for candidate in (
        getattr(session, "num_participants", None),
        getattr(session, "num_expected_participants", None),
        getattr(getattr(session, "config", {}), "get", lambda *_: None)("num_demo_participants"),
    ):
        if candidate not in (None, ""):
            return max(1, _as_int(candidate, fallback or 1))
    return max(1, _as_int(fallback, 1))


def realized_group_size_for_player(player, preferred_size):
    group = getattr(player, "group", None)
    if group is not None:
        try:
            realized = getattr(group, "realized_group_size", None)
            if realized not in (None, 0, ""):
                return max(1, _as_int(realized, preferred_size))
        except Exception:
            pass
        try:
            players_in_group = group.get_players()
            if players_in_group:
                return len(players_in_group)
        except Exception:
            pass
    return max(1, _as_int(preferred_size, 1))
