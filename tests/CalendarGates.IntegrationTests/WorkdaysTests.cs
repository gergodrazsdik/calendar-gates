namespace CalendarGates.IntegrationTests;

public class WorkdaysTests : ApiTestBase
{
    [Test]
    public async Task CountsWorkdaysInclusive()
    {
        var json = await GetJsonAsync("/api/workdays?from=2026-10-12&to=2026-10-18");

        await Assert.That(json.GetProperty("from").GetString()).IsEqualTo("2026-10-12");
        await Assert.That(json.GetProperty("to").GetString()).IsEqualTo("2026-10-18");
        await Assert.That(json.GetProperty("workdays").GetInt32()).IsEqualTo(5);
    }

    [Test]
    public async Task AllowsExactlyTenYears()
    {
        var json = await GetJsonAsync("/api/workdays?from=2026-02-12&to=2036-02-12");

        await Assert.That(json.GetProperty("workdays").GetInt32()).IsEqualTo(2609);
    }

    [Test]
    [Arguments("/api/workdays", new[] { "from", "to" })]
    [Arguments("/api/workdays?from=2026-10-12", new[] { "to" })]
    [Arguments("/api/workdays?from=yesterday&to=2026-10-12", new[] { "from" })]
    [Arguments("/api/workdays?from=2026-10-18&to=2026-10-12", new[] { "to" })] // reversed
    [Arguments("/api/workdays?from=2026-02-12&to=2036-02-13", new[] { "to" })] // > 10 years
    public async Task RejectsInvalidRanges(string path, string[] fields)
    {
        await AssertValidationProblemAsync(path, fields);
    }
}
