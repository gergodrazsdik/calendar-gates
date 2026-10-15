namespace CalendarGates.Api.Domain;

public static class Friday13Calculator
{
    public static IReadOnlyList<DateOnly> InYear(int year)
    {
        Years.ThrowIfUnsupported(year);
        return
        [
            .. Enumerable
                .Range(1, 12)
                .Select(month => new DateOnly(year, month, 13))
                .Where(date => date.DayOfWeek == DayOfWeek.Friday),
        ];
    }

    /// <summary>The first Friday the 13th on or after <paramref name="from"/>, or null past year 9999.</summary>
    public static DateOnly? NextOnOrAfter(DateOnly from)
    {
        // Months counted from year 0; every 14-month window contains a Friday the 13th.
        var month = from.Year * 12 + from.Month - 1 + (from.Day > 13 ? 1 : 0);
        for (; ; month++)
        {
            var year = month / 12;
            if (year > DateOnly.MaxValue.Year)
            {
                return null;
            }

            var candidate = new DateOnly(year, month % 12 + 1, 13);
            if (candidate.DayOfWeek == DayOfWeek.Friday)
            {
                return candidate;
            }
        }
    }
}
