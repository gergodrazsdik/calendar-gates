using System.Globalization;
using System.Text.Json.Serialization;

namespace CalendarGates.Api.Domain;

public sealed record IsoWeekInfo(
    DateOnly Date,
    [property: JsonPropertyName("year")] int IsoYear,
    int Week,
    string Parity
);

public static class IsoWeekCalculator
{
    public static IsoWeekInfo For(DateOnly date)
    {
        var week = ISOWeek.GetWeekOfYear(date);
        return new IsoWeekInfo(date, ISOWeek.GetYear(date), week, week % 2 == 0 ? "even" : "odd");
    }
}
