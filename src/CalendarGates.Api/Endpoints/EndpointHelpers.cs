using System.Globalization;

namespace CalendarGates.Api.Endpoints;

internal static class EndpointHelpers
{
    public const string DateFormat = "yyyy-MM-dd";

    /// <summary>Today's date in UTC (the chiseled image has no time zone data, so UTC is deliberate).</summary>
    public static DateOnly Today(this TimeProvider time) =>
        DateOnly.FromDateTime(time.GetUtcNow().UtcDateTime);

    public static bool TryParseDate(string? value, out DateOnly date) =>
        DateOnly.TryParseExact(
            value,
            DateFormat,
            CultureInfo.InvariantCulture,
            DateTimeStyles.None,
            out date
        );

    public static string InvalidDateMessage(string? value) =>
        string.IsNullOrEmpty(value)
            ? $"A date is required ({DateFormat})."
            : $"'{value}' is not a valid date; expected {DateFormat}.";
}
