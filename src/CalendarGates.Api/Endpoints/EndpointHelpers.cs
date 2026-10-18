using System.Globalization;
using CalendarGates.Api.Domain;

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

    /// <summary>
    /// A year from the query string. Bound as a string on purpose: an <c>int?</c> parameter makes an
    /// unparsable value a binding failure, which never reaches the validation filter, so the caller
    /// got a 400 with no <c>errors</c> in Production and a 500 in Development.
    /// </summary>
    public static bool TryParseYear(string? value, out int year) =>
        int.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out year)
        && Years.IsSupported(year);

    public static string InvalidYearMessage(string? value) =>
        string.IsNullOrEmpty(value)
            ? $"A year is required ({Years.Min}-{Years.Max})."
            : $"'{value}' is not a supported year; expected {Years.Min}-{Years.Max}.";

    public static string InvalidDateMessage(string? value) =>
        string.IsNullOrEmpty(value)
            ? $"A date is required ({DateFormat})."
            : $"'{value}' is not a valid date; expected {DateFormat}.";
}
