"""Module for TimeIt."""
import os
import sys
import time
import asyncio
import decimal
import textwrap
from contextlib import contextmanager
import discord
from discord.ext import commands
from redbot.core import checks
from redbot.core.dev_commands import Dev
from redbot.core.utils.chat_formatting import box


@contextmanager
def silence_stdout():
    """Context manager to direct stdout to null."""
    new_target = open(os.devnull, "w")
    old_target, sys.stdout = sys.stdout, new_target
    try:
        yield new_target
    finally:
        sys.stdout = old_target


def _cleanup_code(code):
    # Try codeblock
    if code.startswith("```") and code.endswith("```"):
        lines = code.split("\n")
        if len(lines) == 1:
            return code.strip('`')
        # codeblock's first line is ```lang
        lines.pop(0)
        # codeblock's last line ends with ```
        if lines[-1] == "```":
            lines.pop(-1)
        else:
            lines[-1] = lines[-1][:-3]
        return "\n".join(lines)
    # try inline
    if code.startswith("`") and code.endswith("`"):
        if "\n" in code:
            print("error")
            raise commands.BadArgument(
                "Inline code must not include line breaks")
        return code.strip("`")
    return code


class FuncConverter(commands.Converter):
    """Convert inline code or codeblocks into the body of an async function."""

    async def convert(self, ctx: commands.Context, argument: str):
        """Convert the code to an async function."""
        code = _cleanup_code(argument)
        if "def func():" not in code:
            code = "def func():\n" + textwrap.indent(code, '  ')
            if any(s in code for s in ("await", "async for", "async with")):
                code = "async " + code
        env = {'ctx': ctx, 'discord': discord, 'commands': commands}
        try:
            exec(code, env)  # pylint: disable=exec-used
        except SyntaxError as err:
            raise commands.BadArgument(Dev.get_syntax_error(err))

        return env['func']


class TimeIt:
    """Check performance time of async functions in discord."""

    @staticmethod
    def _sanitize_output(ctx: commands.Context, input_: str) -> str:
        token = ctx.bot.http.token
        replacement = "[EXPUNGED]"
        result = input_.replace(token, replacement)
        result = result.replace(token.lower(), replacement)
        result = result.replace(token.upper(), replacement)
        return result

    @commands.command()
    @checks.is_owner()
    async def timeit(self, ctx: commands.Context, *, func: FuncConverter):
        """Evaluate code and then time a function or coro.

        <code> must be in a codeblock if there are multiple lines.

        If a callable or coroutine named "func" is declared, it will be the
        timed function. Otherwise the code will be wrapped in a function or
        coroutine and timed. This function must be declared with a "def"
        statement, it cannot be a lambda declaration.

        Note that if "func" is defined, you can only await coroutines from
        within in an async function.

        Environment variables are:
            ctx
            discord
            commands
        """
        await ctx.send("*Evaluating time...*")
        speed = _evaluate_func_speed
        if asyncio.iscoroutinefunction(func):
            speed = _evaluate_coro_speed
        try:
            times = await asyncio.wait_for(speed(func), timeout=15.0)
        except asyncio.TimeoutError:
            await ctx.send("Waited 15 seconds, task still isn't complete.")
        except Exception as err:  # pylint: disable=broad-except
            await ctx.send(box(repr(err), lang='py'))
        else:
            count = len(times)
            total = sum(times)
            avg = total / float(count)
            avg = _get_time_spec(avg)
            if count < 4:
                await ctx.send(
                    box("Loops: {}\n"
                        "Average time: {}".format(count, avg),
                        lang='py'))
                return
            best_3 = tuple(map(_get_time_spec, times[:3]))
            await ctx.send(
                box("Loops: {}\n"
                    "Average time: {}\n"
                    "Top 3 times: {}, {}, {}".format(count, avg, *best_3),
                    lang='py'))


async def _evaluate_coro_speed(func):
    async def _time_coro():
        with silence_stdout():
            start = time.perf_counter()
            await func()
            return time.perf_counter() - start

    times = []
    time_passed = 0.0
    max_count = 100000
    while len(times) < max_count:
        max_count = _get_max_count(time_passed) or max_count
        _time = await _time_coro()
        times.append(_time)
        time_passed += _time

    return tuple(sorted(times))


async def _evaluate_func_speed(func):
    def _time_func():
        with silence_stdout():
            start = time.perf_counter()
            func()
            return time.perf_counter() - start

    times = []
    time_passed = 0.0
    max_count = 100000
    while len(times) < max_count:
        max_count = _get_max_count(time_passed) or max_count
        _time = _time_func()
        times.append(_time)
        time_passed += _time

    return tuple(sorted(times))


def _get_max_count(time_passed):
    if time_passed > 12.0:
        return 1
    if time_passed > 10.0:
        return 10
    elif time_passed > 7.5:
        return 100
    elif time_passed > 5.0:
        return 500
    elif time_passed > 3.0:
        return 1000
    elif time_passed > 1.0:
        return 10000


decimal.setcontext(decimal.Context(prec=8))


def _get_time_spec(delay: float):
    units = "s", "ms", "us", "ns", "ps"
    dec = decimal.Decimal(delay).normalize()
    dec = dec.to_eng_string()
    if "E-" in dec:
        index = int(dec[-1]) // 3
        dec = dec[:-3]
    else:
        index = 0
        if "E+" in dec:
            dec = str(decimal.Decimal(delay))
    unit = units[index]
    return dec + unit
