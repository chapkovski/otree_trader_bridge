import os
import random
import traceback

from otree.api import *
from .utils import (
    _as_bool,
    _as_float,
    _as_int,
    _get_json,
    _log,
    _normalize_http_base,
    _post_json,
    _resolve_day_duration_minutes,
    _ws_base_from_http,
)

doc = """
oTree app that initializes one external trader UUID per group participant and
opens a websocket-driven trading page.
"""


class C(BaseConstants):
    """
    Constants class for the trader bridge application.

    Attributes:
        NAME_IN_URL (str): URL identifier for the app.
        PLAYERS_PER_GROUP (None): No group structure enforced.
        NUM_ROUNDS (int): Number of rounds, read from NUM_ROUNDS environment variable (default: 2).
        
        DEFAULT_TRADING_API_BASE (str): Base URL for the trading API server.
        DEFAULT_API_TIMEOUT_SECONDS (int): Timeout duration for API requests in seconds.
        DEFAULT_TRADING_DAY_DURATION (int): Duration of a trading day in simulation time units.
        DEFAULT_STEP (int): Single step increment for simulation progression.
        DEFAULT_MAX_ORDERS_PER_MINUTE (int): Maximum number of orders a player can submit per minute.
        DEFAULT_INITIAL_MIDPOINT (int): Initial midpoint price for traded assets.
        DEFAULT_INITIAL_SPREAD (int): Initial bid-ask spread for traded assets.
        DEFAULT_INITIAL_CASH (int): Initial cash allocation per player.
        DEFAULT_INITIAL_STOCKS (int): Initial stock allocation per player.
        DEFAULT_ALERT_STREAK_FREQUENCY (int): Frequency threshold for alert notifications.
        DEFAULT_ALERT_WINDOW_SIZE (int): Window size for calculating alert metrics.
        DEFAULT_ALLOW_SELF_TRADE (bool): Whether self-trading is permitted.
        DEFAULT_GROUP_SIZE (int): Number of players per trading group.
        DEFAULT_HYBRID_NOISE_TRADERS (int): Number of noise trader agents in hybrid treatment groups.
        
        TREATMENTS (tuple): Available treatment conditions.
        TREATMENT_MARKET_DESIGN (dict): Maps treatments to market design types (gamified or non-gamified).
        TREATMENT_GROUP_COMPOSITION (dict): Maps treatments to group composition types (human_only or hybrid).
    """
    NAME_IN_URL = "trader_bridge"
    PLAYERS_PER_GROUP = None
    NUM_ROUNDS = int(os.getenv("NUM_ROUNDS", 2))

    DEFAULT_TRADING_API_BASE = "http://127.0.0.1:8001"
    DEFAULT_API_TIMEOUT_SECONDS = 20
    DEFAULT_TRADING_DAY_DURATION = 2
    DEFAULT_STEP = 1
    DEFAULT_MAX_ORDERS_PER_MINUTE = 30
    DEFAULT_INITIAL_MIDPOINT = 100
    DEFAULT_INITIAL_SPREAD = 10
    DEFAULT_INITIAL_CASH = 2600
    DEFAULT_INITIAL_STOCKS = 20
    DEFAULT_ALERT_STREAK_FREQUENCY = 3
    DEFAULT_ALERT_WINDOW_SIZE = 5
    DEFAULT_ALLOW_SELF_TRADE = True
    DEFAULT_GROUP_SIZE = 2
    DEFAULT_HYBRID_NOISE_TRADERS = 1
    TREATMENTS = ("gh", "nh", "gm", "nm")
    TREATMENT_MARKET_DESIGN = {
        "gh": "gamified",
        "gm": "gamified",
        "nh": "non_gamified",
        "nm": "non_gamified",
    }
    TREATMENT_GROUP_COMPOSITION = {
        "gh": "human_only",
        "nh": "human_only",
        "gm": "hybrid",
        "nm": "hybrid",
    }
    DIVIDEND_VALUES = (0, 8, 16, 24)


class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    trading_session_uuid = models.StringField(blank=True)
    trading_api_base = models.StringField(blank=True)
    trading_ws_base = models.StringField(blank=True)
    trading_init_error = models.LongStringField(blank=True)
    trading_day_duration_minutes = models.IntegerField(initial=C.DEFAULT_TRADING_DAY_DURATION)
    treatment = models.StringField(initial="gh")
    market_design = models.StringField(initial="gamified")
    group_composition = models.StringField(initial="human_only")


class Player(BasePlayer):
    trader_uuid = models.StringField(blank=True)
    current_cash = models.FloatField(initial=0)
    num_shares = models.FloatField(initial=0)
    dividend_per_share = models.FloatField(initial=0)
    dividend_cash = models.FloatField(initial=0)
    cash_after_dividend = models.FloatField(initial=0)
    daybreak_snapshot_error = models.LongStringField(blank=True)


def creating_session(subsession: Subsession):
    _log(
        "creating_session start",
        round_number=subsession.round_number,
        subsession_id=getattr(subsession, "id", None),
        session_code=getattr(subsession.session, "code", None),
    )
    if subsession.round_number != 1:
        subsession.group_like_round(1)
        for group in subsession.get_groups():
            round_1_group = group.in_round(1)
            group.treatment = round_1_group.treatment
            group.market_design = round_1_group.market_design
            group.group_composition = round_1_group.group_composition
        _log("creating_session copied group matrix + treatments from round 1", round_number=subsession.round_number)
        return

    players = subsession.get_players()
    if not players:
        _log("creating_session found no players")
        return

    _log("creating_session players loaded", player_ids=[p.id_in_subsession for p in players], num_players=len(players))

    desired_size = _as_int(subsession.session.config.get("players_per_group", C.DEFAULT_GROUP_SIZE), C.DEFAULT_GROUP_SIZE)
    desired_size = max(2, desired_size)
    _log("creating_session using group size", requested=subsession.session.config.get("players_per_group"), applied=desired_size)

    matrix = []
    for idx in range(0, len(players), desired_size):
        matrix.append(players[idx: idx + desired_size])
    subsession.set_group_matrix(matrix)
    _log(
        "creating_session group matrix set",
        group_sizes=[len(g) for g in matrix],
        groups=[[p.id_in_subsession for p in g] for g in matrix],
    )

    configured_treatments = _parse_treatments(subsession.session.config.get("treatments"))
    groups = subsession.get_groups()
    for idx, group in enumerate(groups):
        treatment = configured_treatments[idx % len(configured_treatments)]
        _set_group_treatment(group, treatment)
    _log(
        "creating_session assigned treatments",
        treatments=[g.treatment for g in groups],
        market_designs=[g.market_design for g in groups],
        group_compositions=[g.group_composition for g in groups],
    )


def _parse_treatments(raw_value):
    if raw_value is None:
        return list(C.TREATMENTS)
    if isinstance(raw_value, str):
        candidate_values = [x.strip().lower() for x in raw_value.split(",")]
    elif isinstance(raw_value, (list, tuple)):
        candidate_values = [str(x).strip().lower() for x in raw_value]
    else:
        return list(C.TREATMENTS)
    filtered = [x for x in candidate_values if x in C.TREATMENTS]
    return filtered or list(C.TREATMENTS)


def _set_group_treatment(group: Group, treatment: str):
    treatment_value = str(treatment or "").strip().lower()
    if treatment_value not in C.TREATMENTS:
        treatment_value = C.TREATMENTS[0]
    group.treatment = treatment_value
    group.market_design = C.TREATMENT_MARKET_DESIGN[treatment_value]
    group.group_composition = C.TREATMENT_GROUP_COMPOSITION[treatment_value]


def _build_initiate_payload(group: Group, num_players: int):
    cfg = group.session.config
    hybrid_noise_traders = _as_int(
        cfg.get("hybrid_noise_traders", C.DEFAULT_HYBRID_NOISE_TRADERS),
        C.DEFAULT_HYBRID_NOISE_TRADERS,
    )
    # TEMP: force noise traders in all treatments (including "human_only") for debugging/demo runs.
    # Revert to the composition-based condition once we restore treatment-specific behavior.
    num_noise_traders = max(0, hybrid_noise_traders)
    day_duration_minutes = _resolve_day_duration_minutes(cfg, C.DEFAULT_TRADING_DAY_DURATION)
    return dict(
        num_human_traders=num_players,
        num_noise_traders=num_noise_traders,
        # Backend expects total market duration (minutes). We run one market over all rounds.
        trading_day_duration=max(1, day_duration_minutes * C.NUM_ROUNDS),
        step=_as_int(
            cfg.get("step", C.DEFAULT_STEP),
            C.DEFAULT_STEP,
        ),
        max_orders_per_minute=_as_int(
            cfg.get("max_orders_per_minute", C.DEFAULT_MAX_ORDERS_PER_MINUTE),
            C.DEFAULT_MAX_ORDERS_PER_MINUTE,
        ),
        initial_midpoint=float(cfg.get("initial_midpoint", C.DEFAULT_INITIAL_MIDPOINT)),
        initial_spread=float(cfg.get("initial_spread", C.DEFAULT_INITIAL_SPREAD)),
        initial_cash=float(cfg.get("initial_cash", C.DEFAULT_INITIAL_CASH)),
        initial_stocks=_as_int(cfg.get("initial_stocks", C.DEFAULT_INITIAL_STOCKS), C.DEFAULT_INITIAL_STOCKS),
        alert_streak_frequency=_as_int(
            cfg.get("alert_streak_frequency", C.DEFAULT_ALERT_STREAK_FREQUENCY),
            C.DEFAULT_ALERT_STREAK_FREQUENCY,
        ),
        alert_window_size=_as_int(cfg.get("alert_window_size", C.DEFAULT_ALERT_WINDOW_SIZE), C.DEFAULT_ALERT_WINDOW_SIZE),
        allow_self_trade=_as_bool(cfg.get("allow_self_trade", C.DEFAULT_ALLOW_SELF_TRADE), C.DEFAULT_ALLOW_SELF_TRADE),
    )


def _pause_trading_session(group: Group):
    if not group.trading_session_uuid or not group.trading_api_base:
        raise RuntimeError("Cannot pause: missing trading session UUID or API base.")
    cfg = group.session.config
    timeout_seconds = _as_int(
        cfg.get("trading_api_timeout_seconds", C.DEFAULT_API_TIMEOUT_SECONDS),
        C.DEFAULT_API_TIMEOUT_SECONDS,
    )
    pause_url = f"{group.trading_api_base}/trading_session/{group.trading_session_uuid}/pause"
    response = _post_json(pause_url, {}, timeout_seconds)
    return response.get("data") or {}


def _resume_trading_session(group: Group):
    if not group.trading_session_uuid or not group.trading_api_base:
        raise RuntimeError("Cannot resume: missing trading session UUID or API base.")
    cfg = group.session.config
    timeout_seconds = _as_int(
        cfg.get("trading_api_timeout_seconds", C.DEFAULT_API_TIMEOUT_SECONDS),
        C.DEFAULT_API_TIMEOUT_SECONDS,
    )
    resume_url = f"{group.trading_api_base}/trading_session/{group.trading_session_uuid}/resume"
    response = _post_json(resume_url, {}, timeout_seconds)
    return response.get("data") or {}


def _group_init_error(group: Group) -> str:
    return str(group.field_maybe_none("trading_init_error") or "")


def _copy_round_1_trading_state(group: Group):
    round_1_group = group.in_round(1)
    group.trading_session_uuid = round_1_group.trading_session_uuid
    group.trading_api_base = round_1_group.trading_api_base
    group.trading_ws_base = round_1_group.trading_ws_base
    group.trading_day_duration_minutes = round_1_group.trading_day_duration_minutes
    group.trading_init_error = _group_init_error(round_1_group)
    for player in group.get_players():
        round_1_player = player.in_round(1)
        player.trader_uuid = round_1_player.trader_uuid or str(player.participant.vars.get("trader_uuid") or "")
        if player.trader_uuid:
            player.participant.vars["trader_uuid"] = player.trader_uuid


def _fetch_trader_info(group: Group, trader_uuid: str):
    trader_id = str(trader_uuid or "").strip()
    if not trader_id or not group.trading_api_base:
        return {}
    cfg = group.session.config
    timeout_seconds = _as_int(
        cfg.get("trading_api_timeout_seconds", C.DEFAULT_API_TIMEOUT_SECONDS),
        C.DEFAULT_API_TIMEOUT_SECONDS,
    )
    response = _get_json(f"{group.trading_api_base}/trader_info/{trader_id}", timeout_seconds)
    return response.get("data") or {}


def _apply_dividend_to_trader(group: Group, trader_uuid: str, trading_day: int, dividend_per_share: float):
    trader_id = str(trader_uuid or "").strip()
    if not trader_id:
        return {}
    cfg = group.session.config
    timeout_seconds = _as_int(
        cfg.get("trading_api_timeout_seconds", C.DEFAULT_API_TIMEOUT_SECONDS),
        C.DEFAULT_API_TIMEOUT_SECONDS,
    )
    payload = {
        "trading_day": int(trading_day),
        "dividend_per_share": float(dividend_per_share),
    }
    url = f"{group.trading_api_base}/trader/{trader_id}/apply_dividend"
    response = _post_json(url, payload, timeout_seconds)
    return response.get("data") or {}


def _capture_daybreak_state(group: Group):
    completed_day = int(group.subsession.round_number)
    for player in group.get_players():
        trader_id = str(player.trader_uuid or "").strip()
        if not trader_id:
            continue
        snapshot_error = ""
        snapshot = {}
        try:
            snapshot = _fetch_trader_info(group, trader_id)
        except Exception as exc:
            snapshot_error = str(exc)
            _log(
                "_capture_daybreak_state trader_info failed",
                round_number=completed_day,
                player_id=player.id_in_subsession,
                trader_uuid=trader_id,
                error=snapshot_error,
            )
        shares = _as_float(snapshot.get("shares", 0), 0.0)
        dividend_per_share = float(random.choice(C.DIVIDEND_VALUES))
        apply_result = _apply_dividend_to_trader(
            group=group,
            trader_uuid=trader_id,
            trading_day=completed_day,
            dividend_per_share=dividend_per_share,
        )

        player.current_cash = _as_float(apply_result.get("cash_before_dividend", snapshot.get("cash", 0)), 0.0)
        player.num_shares = _as_float(apply_result.get("shares", shares), shares)
        player.dividend_per_share = _as_float(
            apply_result.get("dividend_per_share", dividend_per_share),
            dividend_per_share,
        )
        player.dividend_cash = _as_float(
            apply_result.get("dividend_cash", player.num_shares * player.dividend_per_share),
            0.0,
        )
        player.cash_after_dividend = _as_float(
            apply_result.get("cash_after_dividend", player.current_cash + player.dividend_cash),
            player.current_cash + player.dividend_cash,
        )
        player.daybreak_snapshot_error = snapshot_error

        _log(
            "_capture_daybreak_state stored player daybreak values",
            round_number=completed_day,
            player_id=player.id_in_subsession,
            trader_uuid=trader_id,
            current_cash=player.current_cash,
            num_shares=player.num_shares,
            dividend_per_share=player.dividend_per_share,
            dividend_cash=player.dividend_cash,
            cash_after_dividend=player.cash_after_dividend,
            snapshot_error=snapshot_error,
            apply_result=apply_result,
        )


def after_all_players_arrive(group: Group):
    _log(
        "after_all_players_arrive start",
        group_id=getattr(group, "id", None),
        subsession_id=getattr(group.subsession, "id", None),
        session_code=getattr(group.session, "code", None),
        round_number=getattr(group.subsession, "round_number", None),
    )
    players = sorted(group.get_players(), key=lambda p: p.id_in_group)
    num_players = len(players)
    cfg = group.session.config
    _log(
        "after_all_players_arrive loaded players and config",
        num_players=num_players,
        player_ids=[p.id_in_group for p in players],
        session_config=dict(cfg),
    )

    http_base = _normalize_http_base(
        cfg.get("trading_api_base", os.getenv("TRADING_API_BASE", C.DEFAULT_TRADING_API_BASE)),
        C.DEFAULT_TRADING_API_BASE,
    )
    timeout_seconds = _as_int(
        cfg.get("trading_api_timeout_seconds", C.DEFAULT_API_TIMEOUT_SECONDS),
        C.DEFAULT_API_TIMEOUT_SECONDS,
    )

    group.trading_api_base = http_base
    group.trading_ws_base = _ws_base_from_http(http_base)
    group.trading_day_duration_minutes = _resolve_day_duration_minutes(cfg, C.DEFAULT_TRADING_DAY_DURATION)
    _log(
        "after_all_players_arrive resolved endpoints",
        http_base=http_base,
        ws_base=group.trading_ws_base,
        timeout_seconds=timeout_seconds,
        trading_day_duration_minutes=group.trading_day_duration_minutes,
        treatment=group.treatment,
        market_design=group.market_design,
        group_composition=group.group_composition,
    )

    try:
        payload = _build_initiate_payload(group, num_players)
        _log("after_all_players_arrive built payload", payload=payload)
        response = _post_json(f"{http_base}/trading/initiate", payload, timeout_seconds)
        _log("after_all_players_arrive received response", response=response)
        data = response.get("data") or {}
        _log("after_all_players_arrive extracted data section", data=data, data_keys=list(data.keys()))

        trading_session_uuid = data.get("trading_session_uuid")
        human_traders = data.get("human_traders") or []
        _log(
            "after_all_players_arrive parsed trading identifiers",
            trading_session_uuid=trading_session_uuid,
            human_traders=human_traders,
            human_traders_count=len(human_traders),
        )
        if not trading_session_uuid:
            _log("after_all_players_arrive validation failed: missing trading_session_uuid")
            raise RuntimeError("Trading API response missing data.trading_session_uuid.")
        if len(human_traders) < num_players:
            _log(
                "after_all_players_arrive validation failed: not enough human traders",
                expected=num_players,
                received=len(human_traders),
            )
            raise RuntimeError(
                f"Trading API returned {len(human_traders)} human trader UUIDs for {num_players} players."
            )

        group.trading_session_uuid = str(trading_session_uuid)
        group.trading_init_error = ""
        _log("after_all_players_arrive storing success state", trading_session_uuid=group.trading_session_uuid)

        for player, trader_uuid in zip(players, human_traders):
            trader_id = str(trader_uuid)
            player.trader_uuid = trader_id
            player.participant.vars["trader_uuid"] = trader_id
            _log(
                "after_all_players_arrive assigned trader UUID",
                player_id_in_group=player.id_in_group,
                player_id_in_subsession=player.id_in_subsession,
                trader_uuid=trader_id,
            )
        _log("after_all_players_arrive completed successfully")
    except Exception as exc:
        group.trading_session_uuid = ""
        group.trading_init_error = str(exc)
        _log(
            "after_all_players_arrive failed",
            error=str(exc),
            error_type=str(type(exc)),
            traceback=traceback.format_exc(),
        )
        for player in players:
            player.trader_uuid = ""
            _log(
                "after_all_players_arrive cleared player trader_uuid due to error",
                player_id_in_group=player.id_in_group,
                player_id_in_subsession=player.id_in_subsession,
            )


class Intro(Page):
    pass


class SyncTradingSession(WaitPage):
    title_text = "Preparing Trading Session"
    body_text = "Please wait while the group trading session is created."
    after_all_players_arrive = after_all_players_arrive

    @staticmethod
    def is_displayed(player: Player):
        return player.round_number == 1


def resume_trading_after_wait(group: Group):
    _copy_round_1_trading_state(group)
    if _group_init_error(group):
        return
    if not group.trading_session_uuid:
        group.trading_init_error = "Missing round-1 trading session UUID; cannot resume."
        return
    try:
        result = _resume_trading_session(group)
        _log(
            "resume_trading_after_wait succeeded",
            round_number=group.subsession.round_number,
            trading_session_uuid=group.trading_session_uuid,
            result=result,
        )
        group.trading_init_error = ""
    except Exception as exc:
        group.trading_init_error = str(exc)
        _log(
            "resume_trading_after_wait failed",
            round_number=group.subsession.round_number,
            trading_session_uuid=group.trading_session_uuid,
            error=str(exc),
            traceback=traceback.format_exc(),
        )


def pause_trading_after_wait(group: Group):
    _copy_round_1_trading_state(group)
    if _group_init_error(group):
        return
    if not group.trading_session_uuid:
        group.trading_init_error = "Missing trading session UUID; cannot pause."
        return
    try:
        result = _pause_trading_session(group)
        _capture_daybreak_state(group)
        _log(
            "pause_trading_after_wait succeeded",
            round_number=group.subsession.round_number,
            trading_session_uuid=group.trading_session_uuid,
            result=result,
        )
        group.trading_init_error = ""
    except Exception as exc:
        group.trading_init_error = str(exc)
        _log(
            "pause_trading_after_wait failed",
            round_number=group.subsession.round_number,
            trading_session_uuid=group.trading_session_uuid,
            error=str(exc),
            traceback=traceback.format_exc(),
        )


class PauseTradingSession(WaitPage):
    title_text = "Pausing Market"
    body_text = "Please wait while the market is paused for the intermission."
    after_all_players_arrive = pause_trading_after_wait

    @staticmethod
    def is_displayed(player: Player):
        return (
            player.round_number < C.NUM_ROUNDS
            and not _group_init_error(player.group)
            and bool(player.trader_uuid)
        )


class ResumeTradingSession(WaitPage):
    title_text = "Waiting To Resume Market"
    body_text = "Please wait for all participants to arrive. Trading will resume once everyone is ready."
    after_all_players_arrive = resume_trading_after_wait

    @staticmethod
    def is_displayed(player: Player):
        return player.round_number > 1


class InitFailed(Page):
    @staticmethod
    def is_displayed(player: Player):
        return bool(_group_init_error(player.group))

    @staticmethod
    def vars_for_template(player: Player):
        return dict(
            error_message=_group_init_error(player.group),
            trading_api_base=player.group.trading_api_base,
        )


class TradePage(Page):
    use_standard_layout = False

    @staticmethod
    def is_displayed(player: Player):
        return not _group_init_error(player.group) and bool(player.trader_uuid)

    @staticmethod
    def vars_for_template(player: Player):
        ws_url = f"{player.group.trading_ws_base}/trader/{player.trader_uuid}"
        return dict(
            ws_url=ws_url,
            trader_uuid=player.trader_uuid,
            trading_api_base=player.group.trading_api_base,
            trading_session_uuid=player.group.trading_session_uuid,
            treatment=player.group.treatment,
            market_design=player.group.market_design,
            group_composition=player.group.group_composition,
        )

    @staticmethod
    def js_vars(player: Player):
        ws_url = f"{player.group.trading_ws_base}/trader/{player.trader_uuid}"
        gamified = player.group.market_design == "gamified"
        day_duration_minutes = _resolve_day_duration_minutes(player.session.config, C.DEFAULT_TRADING_DAY_DURATION)
        return dict(
            wsUrl=ws_url,
            wsBase=player.group.trading_ws_base,
            traderUuid=player.trader_uuid,
            httpUrl=f"{player.group.trading_api_base}/",
            tradingApiBase=player.group.trading_api_base,
            tradingSessionUuid=player.group.trading_session_uuid,
            playerIdInGroup=player.id_in_group,
            gamified=gamified,
            treatment=player.group.treatment,
            marketDesign=player.group.market_design,
            groupComposition=player.group.group_composition,
            roundNumber=player.round_number,
            totalRounds=C.NUM_ROUNDS,
            dayDurationMinutes=day_duration_minutes,
        )

    @staticmethod
    def get_timeout_seconds(player: Player):
        duration_minutes = _resolve_day_duration_minutes(player.session.config, C.DEFAULT_TRADING_DAY_DURATION)
        # Day 1 is a hard stop to intermission; final day includes small closure buffer.
        if player.round_number < C.NUM_ROUNDS:
            return max(15, int(duration_minutes * 60))
        return max(15, int(duration_minutes * 60) + 30)


class DayBreak(Page):
    @staticmethod
    def is_displayed(player: Player):
        return (
            player.round_number < C.NUM_ROUNDS
            and not _group_init_error(player.group)
            and bool(player.trader_uuid)
        )

    @staticmethod
    def vars_for_template(player: Player):
        _copy_round_1_trading_state(player.group)
        return dict(
            market_number=1,
            completed_day=player.round_number,
            next_day=player.round_number + 1,
            current_cash=player.current_cash,
            num_shares=player.num_shares,
            dividend=player.dividend_per_share,
            dividend_per_share=player.dividend_per_share,
            dividend_cash=player.dividend_cash,
            cash_after_dividend=player.cash_after_dividend,
            snapshot_error=player.daybreak_snapshot_error,
        )


class Results(Page):
    @staticmethod
    def is_displayed(player: Player):
        return player.round_number == C.NUM_ROUNDS


page_sequence = [
    SyncTradingSession,
    ResumeTradingSession,
    InitFailed,
    TradePage,
    PauseTradingSession,
    DayBreak,
    Results,
]

from .export import (
    custom_export,
    custom_export_gamification_ui,
    custom_export_mbo,
    custom_export_mbp1,
    custom_export_messages,
)
