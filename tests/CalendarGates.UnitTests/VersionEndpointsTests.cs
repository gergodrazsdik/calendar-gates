using System.Reflection;
using System.Reflection.Emit;
using CalendarGates.Api.Endpoints;

namespace CalendarGates.UnitTests;

/// <summary>
/// What `/api/version` reports, including the fallbacks. The integration test and the `.http`
/// handler only assert that the two fields are non-empty, so `0.0.0` and `unknown` passed them and
/// nothing described when those appear (F113). The release smoke compares the version with the tag.
/// </summary>
public class VersionEndpointsTests
{
    private static AssemblyBuilder Built(string? informational, string? commit)
    {
        var name = new AssemblyName($"VersionProbe{Guid.NewGuid():N}");
        var assembly = AssemblyBuilder.DefineDynamicAssembly(name, AssemblyBuilderAccess.Run);
        if (informational is not null)
        {
            assembly.SetCustomAttribute(
                new CustomAttributeBuilder(
                    typeof(AssemblyInformationalVersionAttribute).GetConstructor([typeof(string)])!,
                    [informational]
                )
            );
        }

        if (commit is not null)
        {
            assembly.SetCustomAttribute(
                new CustomAttributeBuilder(
                    typeof(AssemblyMetadataAttribute).GetConstructor([
                        typeof(string),
                        typeof(string),
                    ])!,
                    ["Commit", commit]
                )
            );
        }

        return assembly;
    }

    [Test]
    public async Task TakesTheVersionAndCommitFromTheInformationalVersion()
    {
        var version = VersionEndpoints.Read(Built("1.2.3+abc1234", commit: null));

        await Assert.That(version.Version).IsEqualTo("1.2.3");
        await Assert.That(version.Commit).IsEqualTo("abc1234");
    }

    [Test]
    public async Task PrefersTheCommitMetadataOverTheVersionSuffix()
    {
        var version = VersionEndpoints.Read(Built("1.2.3+fromversion", "fromarg"));

        await Assert.That(version.Version).IsEqualTo("1.2.3");
        await Assert.That(version.Commit).IsEqualTo("fromarg");
    }

    [Test]
    [Arguments("1.2.3", null, "1.2.3", "unknown")] // a build with no commit anywhere
    [Arguments(null, null, "0.0.0", "unknown")] // no MinVer tags and no commit: both fallbacks
    [Arguments(null, "abc1234", "0.0.0", "abc1234")]
    public async Task FallsBackWhenTheAttributesAreMissing(
        string? informational,
        string? commit,
        string expectedVersion,
        string expectedCommit
    )
    {
        var version = VersionEndpoints.Read(Built(informational, commit));

        await Assert.That(version.Version).IsEqualTo(expectedVersion);
        await Assert.That(version.Commit).IsEqualTo(expectedCommit);
    }
}
