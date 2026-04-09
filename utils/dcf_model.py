def calculate_dcf(
    fcf: float,
    growth_rate: float,
    terminal_growth: float,
    wacc: float,
    shares_outstanding: float,
    years: int = 5,
) -> dict | None:
    """
    Simple DCF valuation.
    All rates as decimals (e.g. 0.10 for 10%).
    Returns dict with intrinsic_value per share or None on error.
    """
    try:
        if wacc <= terminal_growth:
            return None
        if not all([fcf, shares_outstanding, shares_outstanding > 0]):
            return None

        projected_fcf = [fcf * (1 + growth_rate) ** i for i in range(1, years + 1)]

        terminal_value = projected_fcf[-1] * (1 + terminal_growth) / (wacc - terminal_growth)

        pv_fcfs = sum(cf / (1 + wacc) ** i for i, cf in enumerate(projected_fcf, 1))
        pv_terminal = terminal_value / (1 + wacc) ** years

        enterprise_value = pv_fcfs + pv_terminal
        intrinsic_value = enterprise_value / shares_outstanding

        return {
            'intrinsic_value': intrinsic_value,
            'enterprise_value': enterprise_value,
            'pv_fcfs': pv_fcfs,
            'pv_terminal': pv_terminal,
            'projected_fcf': projected_fcf,
            'terminal_value': terminal_value,
        }
    except Exception:
        return None
