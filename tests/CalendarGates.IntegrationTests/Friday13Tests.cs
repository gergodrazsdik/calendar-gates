using System.Net;
using TUnit.Assertions.Enums;

namespace CalendarGates.IntegrationTests;

public class Friday13Tests : ApiTestBase
{
    [Test]
    public async Task DefaultsToTheCurrentYear()
    {
        var json = await GetJsonAsync("/api/friday13");

        await Assert.That(json.GetProperty("year").GetInt32()).IsEqualTo(2026);
        await Assert.That(json.GetProperty("count").GetInt32()).IsEqualTo(3);
        var dates = json.GetProperty("dates").EnumerateArray().Select(d => d.GetString()!);
        await Assert
            .That(dates)
            .IsEquivalentTo(
                ["2026-02-13", "2026-03-13", "2026-11-13"],
                CollectionOrdering.Matching // the order is the answer, not an accident (F110)
            );
    }

    /// <summary>
    /// 9999-08-13 is the last Friday the 13th that fits in a DateOnly, so the day after it there is
    /// no next one and the endpoint answers 404. Nothing covered that branch (F111).
    /// </summary>
    [Test]
    public async Task NextIsNotFoundPastTheLastFridayThe13th()
    {
        Time.SetUtcNow(new DateTimeOffset(9999, 8, 14, 0, 0, 0, TimeSpan.Zero));

        var problem = await GetJsonAsync("/api/friday13/next", HttpStatusCode.NotFound);

        await Assert.That(problem.GetProperty("status").GetInt32()).IsEqualTo(404);
    }

    [Test]
    public async Task ListsAGivenYear()
    {
        var json = await GetJsonAsync("/api/friday13?year=2025");

        await Assert.That(json.GetProperty("count").GetInt32()).IsEqualTo(1);
        await Assert.That(json.GetProperty("dates")[0].GetString()).IsEqualTo("2025-06-13");
    }

    [Test]
    [Arguments(1582)]
    [Arguments(10000)]
    public async Task RejectsUnsupportedYears(int year)
    {
        await AssertValidationProblemAsync($"/api/friday13?year={year}", "year");
    }

    /// <summary>
    /// A year the framework can't bind used to fail before the validation filter: a 400 with no
    /// `errors` in Production and a 500 here, where the test host runs in Development (F081).
    /// </summary>
    [Test]
    [Arguments("abc")]
    [Arguments("2026.0")]
    [Arguments("99999999999")]
    [Arguments("%20")] // whitespace is not a year; a raw space in a URI is normalised away
    [Arguments("-2026")]
    [Arguments("2026&year=2027")] // a repeated parameter binds as "2026,2027"
    public async Task RejectsAYearItCannotParse(string year)
    {
        await AssertValidationProblemAsync($"/api/friday13?year={year}", "year");
    }

    /// <summary>An empty `year=` means "this year", as an absent parameter does.</summary>
    [Test]
    public async Task AnEmptyYearIsThisYear()
    {
        var json = await GetJsonAsync("/api/friday13?year=");

        await Assert.That(json.GetProperty("year").GetInt32()).IsEqualTo(2026);
    }

    [Test]
    public async Task NextIsTomorrow()
    {
        var json = await GetJsonAsync("/api/friday13/next");

        await Assert.That(json.GetProperty("date").GetString()).IsEqualTo("2026-02-13");
        await Assert.That(json.GetProperty("daysUntil").GetInt32()).IsEqualTo(1);
    }

    [Test]
    public async Task NextIsTodayOnTheDay()
    {
        Time.Advance(TimeSpan.FromDays(1));

        var json = await GetJsonAsync("/api/friday13/next");

        await Assert.That(json.GetProperty("date").GetString()).IsEqualTo("2026-02-13");
        await Assert.That(json.GetProperty("daysUntil").GetInt32()).IsEqualTo(0);
    }
}
