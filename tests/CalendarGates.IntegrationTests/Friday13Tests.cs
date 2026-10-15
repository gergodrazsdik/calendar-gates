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
        await Assert.That(dates).IsEquivalentTo(["2026-02-13", "2026-03-13", "2026-11-13"]);
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
