using CalendarGates.Api.Domain;

namespace CalendarGates.UnitTests;

public class LeapYearCalculatorTests
{
    [Test]
    [Arguments(1900, false)] // divisible by 100, not by 400
    [Arguments(2000, true)] // divisible by 400
    [Arguments(2024, true)]
    [Arguments(2026, false)]
    [Arguments(2100, false)]
    [Arguments(2400, true)]
    public async Task AppliesGregorianRules(int year, bool expected)
    {
        await Assert.That(LeapYearCalculator.IsLeap(year)).IsEqualTo(expected);
    }

    [Test]
    public async Task AgreesWithTheFrameworkForEverySupportedYear()
    {
        for (var year = Years.Min; year <= Years.Max; year++)
        {
            await Assert.That(LeapYearCalculator.IsLeap(year)).IsEqualTo(DateTime.IsLeapYear(year));
        }
    }

    [Test]
    [Arguments(Years.Min - 1)]
    [Arguments(Years.Max + 1)]
    public async Task RejectsUnsupportedYears(int year)
    {
        await Assert
            .That(() => LeapYearCalculator.IsLeap(year))
            .Throws<ArgumentOutOfRangeException>();
    }
}
