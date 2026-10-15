namespace CalendarGates.Api.Domain;

public static class EasterCalculator
{
    /// <summary>Western (Gregorian) Easter: the anonymous Gregorian algorithm (Meeus/Jones/Butcher).</summary>
    public static DateOnly Western(int year)
    {
        Years.ThrowIfUnsupported(year);
        var a = year % 19;
        var b = year / 100;
        var c = year % 100;
        var d = b / 4;
        var e = b % 4;
        var f = (b + 8) / 25;
        var g = (b - f + 1) / 3;
        var h = (19 * a + b - d - g + 15) % 30;
        var i = c / 4;
        var k = c % 4;
        var l = (32 + 2 * e + 2 * i - h - k) % 7;
        var m = (a + 11 * h + 22 * l) / 451;
        var month = (h + l - 7 * m + 114) / 31;
        var day = (h + l - 7 * m + 114) % 31 + 1;
        return new DateOnly(year, month, day);
    }

    /// <summary>Orthodox Easter: the Julian computus (Meeus), converted to a Gregorian date.</summary>
    public static DateOnly Orthodox(int year)
    {
        Years.ThrowIfUnsupported(year);
        var a = year % 4;
        var b = year % 7;
        var c = year % 19;
        var d = (19 * c + 15) % 30;
        var e = (2 * a + 4 * b - d + 34) % 7;
        var month = (d + e + 114) / 31;
        var day = (d + e + 114) % 31 + 1;

        // Julian → Gregorian offset, valid from March 1 of a century year (Easter is always later).
        var century = year / 100;
        var julianToGregorianDays = century - century / 4 - 2;
        return new DateOnly(year, month, day).AddDays(julianToGregorianDays);
    }
}
