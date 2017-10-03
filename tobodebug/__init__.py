"""Tobo's debug tools.

Currently only contains TimeIt."""
from .timeit import TimeIt

def setup(bot):
    """Load tobodebug."""
    bot.add_cog(TimeIt())
