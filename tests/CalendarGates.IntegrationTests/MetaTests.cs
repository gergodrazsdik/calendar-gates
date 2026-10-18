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
    [Arguments(1582)] // just below Years.Min
    [Arguments(10000)] // just above Years.Max
    [Arguments(99999)]
    public async Task LeapYearRejectsUnsupportedYears(int year)
    {
        await AssertValidationProblemAsync($"/api/leap/{year}", "year");
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

    /// <summary>
    /// The document used to say every integer was `[integer, string]` with a digits pattern, because
    /// the web JSON defaults read numbers from strings (F096), and the date parameters had no format
    /// and claimed to be optional (F086). Only the route list was pinned, so neither showed up.
    /// </summary>
    [Test]
    public async Task OpenApiDescribesDatesAndIntegers()
    {
        var json = await GetJsonAsync("/openapi/v1.json");
        var paths = json.GetProperty("paths");

        var workdays = paths
            .GetProperty("/api/workdays")
            .GetProperty("get")
            .GetProperty("parameters")
            .EnumerateArray();
        foreach (var parameter in workdays)
        {
            await Assert.That(parameter.GetProperty("required").GetBoolean()).IsTrue();
            await Assert
                .That(parameter.GetProperty("schema").GetProperty("format").GetString())
                .IsEqualTo("date");
        }

        var date = paths
            .GetProperty("/api/week/{date}")
            .GetProperty("get")
            .GetProperty("parameters")[0]
            .GetProperty("schema");
        await Assert.That(date.GetProperty("format").GetString()).IsEqualTo("date");

        var week = json.GetProperty("components")
            .GetProperty("schemas")
            .GetProperty("IsoWeekInfo")
            .GetProperty("properties")
            .GetProperty("week");
        await Assert.That(week.GetProperty("type").GetString()).IsEqualTo("integer");
        await Assert.That(week.TryGetProperty("pattern", out _)).IsFalse();
    }

    [Test]
    public async Task UnknownRoutesGetProblemDetails()
    {
        var problem = await GetJsonAsync("/api/nothing", HttpStatusCode.NotFound);

        await Assert.That(problem.GetProperty("status").GetInt32()).IsEqualTo(404);
    }
}
