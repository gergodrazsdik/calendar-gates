using CalendarGates.Api.Domain;
using static CalendarGates.UnitTests.TestDates;

namespace CalendarGates.UnitTests;

public class EasterCalculatorTests
{
    // Expected values cross-checked with python-dateutil's easter() (valid 1583–4099).
    [Test]
    [Arguments(1583, "1583-04-10", "1583-04-10")]
    [Arguments(1700, "1700-04-11", "1700-04-11")]
    [Arguments(1900, "1900-04-15", "1900-04-22")]
    [Arguments(2000, "2000-04-23", "2000-04-30")]
    [Arguments(2019, "2019-04-21", "2019-04-28")]
    [Arguments(2024, "2024-03-31", "2024-05-05")] // five weeks apart
    [Arguments(2025, "2025-04-20", "2025-04-20")] // same day
    [Arguments(2026, "2026-04-05", "2026-04-12")]
    [Arguments(2038, "2038-04-25", "2038-04-25")] // latest possible western date
    [Arguments(2285, "2285-03-22", "2285-04-26")] // earliest possible western date
    public async Task ComputesWesternAndOrthodoxEaster(int year, string western, string orthodox)
    {
        await Assert.That(EasterCalculator.Western(year)).IsEqualTo(D(western));
        await Assert.That(EasterCalculator.Orthodox(year)).IsEqualTo(D(orthodox));
    }

    [Test]
    public async Task EasterIsAlwaysASunday()
    {
        for (var year = Years.Min; year <= Years.Max; year++)
        {
            await Assert.That(EasterCalculator.Western(year).DayOfWeek).IsEqualTo(DayOfWeek.Sunday);
            await Assert
                .That(EasterCalculator.Orthodox(year).DayOfWeek)
                .IsEqualTo(DayOfWeek.Sunday);
        }
    }

    [Test]
    [Arguments(1582)]
    [Arguments(10000)]
    public async Task RejectsUnsupportedYears(int year)
    {
        await Assert
            .That(() => EasterCalculator.Western(year))
            .Throws<ArgumentOutOfRangeException>();
        await Assert
            .That(() => EasterCalculator.Orthodox(year))
            .Throws<ArgumentOutOfRangeException>();
    }
}
