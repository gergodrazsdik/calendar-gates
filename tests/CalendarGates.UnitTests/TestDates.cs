using System.Globalization;

namespace CalendarGates.UnitTests;

internal static class TestDates
{
    /// <summary>Attributes can't hold <see cref="DateOnly"/>, so test data uses yyyy-MM-dd strings.</summary>
    public static DateOnly D(string value) =>
        DateOnly.ParseExact(value, "yyyy-MM-dd", CultureInfo.InvariantCulture);
}
