"""A seed prompt for the synthetic lever the registry tests register.

A real module attribute, because `Lever.seed_ref` resolves by import - so a
test that faked the resolution would not exercise the mechanism it exists to
prove.
"""

SEED = (
    "You are a test subsystem. Today is {today}. Consider {n} things and "
    "produce {k} answers as a JSON array, each carrying widget_low_pct and "
    "widget_high_pct.\n" + "Padding to clear the validator's minimum length. " * 6
)
