using System.Net;

namespace CalendarGates.IntegrationTests;

public class EasterTests : ApiTestBase
{
    [Test]
    public async Task ReturnsWesternAndOrthodoxEaster()
    {
        var json = await GetJsonAsync("/api/easter/2026");

        await Assert.That(json.GetProperty("year").GetInt32()).IsEqualTo(2026);
        await Assert.That(json.GetProperty("western").GetString()).IsEqualTo("2026-04-05");
        await Assert.That(json.GetProperty("orthodox").GetString()).IsEqualTo("2026-04-12");
    }

    [Test]
    [Arguments(1582)]
    [Arguments(10000)]
    public async Task RejectsUnsupportedYears(int year)
    {
        await AssertValidationProblemAsync($"/api/easter/{year}", "year");
    }

    [Test]
    public async Task NonNumericYearDoesNotMatchTheRoute()
    {
        await GetJsonAsync("/api/easter/next", HttpStatusCode.NotFound);
    }
}
