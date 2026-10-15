namespace CalendarGates.IntegrationTests;

public class WeekTests : ApiTestBase
{
    [Test]
    public async Task CurrentWeekUsesTodayInUtc()
    {
        var json = await GetJsonAsync("/api/week");

        await Assert.That(json.GetProperty("date").GetString()).IsEqualTo("2026-02-12");
        await Assert.That(json.GetProperty("isoYear").GetInt32()).IsEqualTo(2026);
        await Assert.That(json.GetProperty("week").GetInt32()).IsEqualTo(7);
        await Assert.That(json.GetProperty("parity").GetString()).IsEqualTo("odd");
    }

    [Test]
    public async Task CurrentWeekFollowsTheClock()
    {
        Time.Advance(TimeSpan.FromDays(4)); // Monday 2026-02-16, week 8

        var json = await GetJsonAsync("/api/week");

        await Assert.That(json.GetProperty("week").GetInt32()).IsEqualTo(8);
        await Assert.That(json.GetProperty("parity").GetString()).IsEqualTo("even");
    }

    [Test]
    public async Task WeekOfADateCanBelongToThePreviousIsoYear()
    {
        var json = await GetJsonAsync("/api/week/2027-01-01");

        await Assert.That(json.GetProperty("date").GetString()).IsEqualTo("2027-01-01");
        await Assert.That(json.GetProperty("isoYear").GetInt32()).IsEqualTo(2026);
        await Assert.That(json.GetProperty("week").GetInt32()).IsEqualTo(53);
    }

    [Test]
    [Arguments("not-a-date")]
    [Arguments("2026-13-01")]
    [Arguments("12-02-2026")]
    public async Task RejectsInvalidDates(string date)
    {
        await AssertValidationProblemAsync($"/api/week/{date}", "date");
    }
}
