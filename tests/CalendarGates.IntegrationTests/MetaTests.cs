using System.Net;

namespace CalendarGates.IntegrationTests;

/// <summary>Leap years, version, health, OpenAPI and unknown routes.</summary>
public class MetaTests : ApiTestBase
{
    [Test]
    [Arguments(1900, false)]
    [Arguments(2000, true)]
    public async Task LeapYear(int year, bool isLeap)
    {
        var json = await GetJsonAsync($"/api/leap/{year}");

        await Assert.That(json.GetProperty("year").GetInt32()).IsEqualTo(year);
        await Assert.That(json.GetProperty("isLeap").GetBoolean()).IsEqualTo(isLeap);
    }

    [Test]
    public async Task LeapYearRejectsUnsupportedYears()
    {
        await AssertValidationProblemAsync("/api/leap/99999", "year");
    }

    [Test]
    public async Task VersionReportsVersionAndCommit()
    {
        var json = await GetJsonAsync("/api/version");

        await Assert.That(json.GetProperty("version").GetString()).IsNotNullOrEmpty();
        await Assert.That(json.GetProperty("commit").GetString()).IsNotNullOrEmpty();
    }

    [Test]
    public async Task HealthIsHealthy()
    {
        using var client = Factory.CreateClient();

        var body = await client.GetStringAsync(new Uri("/health", UriKind.Relative));

        await Assert.That(body).IsEqualTo("Healthy");
    }

    [Test]
    public async Task OpenApiListsEveryRoute()
    {
        var json = await GetJsonAsync("/openapi/v1.json");

        var paths = json.GetProperty("paths").EnumerateObject().Select(p => p.Name);
        await Assert
            .That(paths)
            .IsEquivalentTo([
                "/api/week",
                "/api/week/{date}",
                "/api/friday13",
                "/api/friday13/next",
                "/api/easter/{year}",
                "/api/workdays",
                "/api/leap/{year}",
                "/api/version",
            ]);
    }

    [Test]
    public async Task UnknownRoutesGetProblemDetails()
    {
        var problem = await GetJsonAsync("/api/nothing", HttpStatusCode.NotFound);

        await Assert.That(problem.GetProperty("status").GetInt32()).IsEqualTo(404);
    }
}
