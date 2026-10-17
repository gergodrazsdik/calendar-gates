namespace CalendarGates.Api.Domain;

public static class WorkdaysCalculator
{
    public const int MaxSpanYears = 10;

    /// <summary>Monday–Friday days from <paramref name="from"/> to <paramref name="to"/>, both inclusive.</summary>
    public static int Count(DateOnly from, DateOnly to)
    {
        if (to < from)
        {
            throw new ArgumentException("'to' must not be before 'from'.", nameof(to));
        }

        // Both ends of the range count.
        var days = to.DayNumber - from.DayNumber + 1;
        var count = days / 7 * 5;
        var start = (int)from.DayOfWeek;
        for (var i = 0; i < days % 7; i++)
        {
            var dayOfWeek = (DayOfWeek)((start + i) % 7);
            if (dayOfWeek is not (DayOfWeek.Saturday or DayOfWeek.Sunday))
            {
                count++;
            }
        }

        return count;
    }
}
