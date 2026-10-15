using System.Reflection;

namespace CalendarGates.Api.Endpoints;

public sealed record VersionResponse(string Version, string Commit);

public static class VersionEndpoints
{
    private static readonly VersionResponse s_version = Read(typeof(Program).Assembly);

    public static IEndpointRouteBuilder MapVersionEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapGet("/version", () => TypedResults.Ok(s_version))
            .WithTags("Meta")
            .WithName("GetVersion")
            .WithSummary("Build version (MinVer) and commit");
        return app;
    }

    /// <summary>
    /// Version from MinVer's informational version (<c>1.2.3+sha</c>); commit from the
    /// <c>Commit</c> assembly metadata (Docker build arg), else the SDK's <c>+sha</c> suffix.
    /// </summary>
    internal static VersionResponse Read(Assembly assembly)
    {
        var informational =
            assembly
                .GetCustomAttribute<AssemblyInformationalVersionAttribute>()
                ?.InformationalVersion
            ?? "0.0.0";
        var parts = informational.Split('+', 2);
        var commit =
            assembly
                .GetCustomAttributes<AssemblyMetadataAttribute>()
                .FirstOrDefault(a => a.Key == "Commit")
                ?.Value
            ?? (parts.Length > 1 ? parts[1] : "unknown");
        return new VersionResponse(parts[0], commit);
    }
}
