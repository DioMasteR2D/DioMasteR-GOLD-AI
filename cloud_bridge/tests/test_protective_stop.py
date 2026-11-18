from ema_strategy import StrategyConfig, protective_stop


def test_buy_break_even_profit_lock_and_trailing_stages():
    cfg = StrategyConfig(sl_atr=1.5, tp_atr=3.0)
    assert protective_stop("BUY", 100, 94, 106, 102.4, 0.01, cfg) == 100.0
    assert protective_stop("BUY", 100, 100, 106, 103.6, 0.01, cfg) == 100.9
    assert protective_stop("BUY", 100, 100.9, 106, 104.5, 0.01, cfg) == 102.1


def test_sell_break_even_profit_lock_and_trailing_stages():
    cfg = StrategyConfig(sl_atr=1.5, tp_atr=3.0)
    assert protective_stop("SELL", 100, 106, 94, 97.6, 0.01, cfg) == 100.0
    assert protective_stop("SELL", 100, 100, 94, 96.4, 0.01, cfg) == 99.1
    assert protective_stop("SELL", 100, 99.1, 94, 95.5, 0.01, cfg) == 97.9


def test_protective_stop_never_widens_existing_stop():
    cfg = StrategyConfig(sl_atr=1.5, tp_atr=3.0)
    assert protective_stop("BUY", 100, 101, 106, 103.6, 0.01, cfg) is None
    assert protective_stop("SELL", 100, 99, 94, 96.4, 0.01, cfg) is None
