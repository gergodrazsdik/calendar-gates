using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Time.Testing;
using TUnit.AspNetCore;
using TUnit.AspNetCore.Extensions;

namespace CalendarGates.IntegrationTests;

public class CalendarApiFactory : TestWebApplicationFactory<Program>;

/// <summary>
/// Each test gets its own application with the clock fixed at <see cref="Now"/>:
/// a Thursday in ISO week 7, the day before a Friday the 13th.
/// </summary>
public abstract class ApiTestBase : WebApplicationTest<CalendarApiFactory, Program>
{
    public static readonly DateTimeOffset Now = new(2026, 2, 12, 10, 0, 0, TimeSpan.Zero);

    protected FakeTimeProvider Time { get; } = new(Now);

    protected override void ConfigureTestServices(IServiceCollection services) =>
        services.ReplaceService<TimeProvider>(Time);

    /// <summary>GET <paramref name="path"/>, assert status and content type, return the JSON body.</summary>
    protected async Task<JsonElement> GetJsonAsync(
        string path,
        HttpStatusCode expectedStatus = HttpStatusCode.OK
    )
    {
        using var client = Factory.CreateClient();
        using var response = await client.GetAsync(new Uri(path, UriKind.Relative));

        await Assert.That(response.StatusCode).IsEqualTo(expectedStatus);
        var expectedType =
            (int)expectedStatus >= 400 ? "application/problem+json" : "application/json";
        await Assert.That(response.Content.Headers.ContentType?.MediaType).IsEqualTo(expectedType);
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    /// <summary>Assert a 400 ValidationProblem with errors for exactly <paramref name="fields"/>.</summary>
    protected async Task AssertValidationProblemAsync(string path, params string[] fields)
    {
        var problem = await GetJsonAsync(path, HttpStatusCode.BadRequest);

        await Assert.That(problem.GetProperty("status").GetInt32()).IsEqualTo(400);
        var errorKeys = problem.GetProperty("errors").EnumerateObject().Select(p => p.Name);
        await Assert.That(errorKeys).IsEquivalentTo(fields);
    }
}
