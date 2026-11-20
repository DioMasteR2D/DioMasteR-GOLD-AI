from ema_strategy import StrategyConfig, protective_stop


def test_buy_profit_protection_stages():
    cfg = StrategyConfig(sl_atr=1.5, tp_atr=3.0)
    # 0.39R locks $3; 0.70R locks +0.15R; 1.00R locks +0.35R; 1.50R trails 0.80R.
    assert protective_stop("BUY", 100, 94, 106, 101.17, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 100.3
    assert protective_stop("BUY", 100, 94, 106, 102.1, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 100.45
    assert protective_stop("BUY", 100, 94, 106, 103.0, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 101.05
    assert protective_stop("BUY", 100, 94, 106, 104.5, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 102.1


def test_sell_profit_protection_stages():
    cfg = StrategyConfig(sl_atr=1.5, tp_atr=3.0)
    assert protective_stop("SELL", 100, 106, 94, 98.83, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 99.7
    assert protective_stop("SELL", 100, 106, 94, 97.9, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 99.55
    assert protective_stop("SELL", 100, 106, 94, 97.0, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 98.95
    assert protective_stop("SELL", 100, 106, 94, 95.5, 0.01, cfg, initial_risk=3.0, be_profit_price_distance=0.30) == 97.9


def test_protective_stop_never_widens_existing_stop():
    cfg = StrategyConfig(sl_atr=1.5, tp_atr=3.0)
    assert protective_stop("BUY", 100, 101.1, 106, 103.6, 0.01, cfg) is None
    assert protective_stop("SELL", 100, 98.9, 94, 96.4, 0.01, cfg) is None
