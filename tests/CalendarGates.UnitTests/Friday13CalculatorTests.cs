using CalendarGates.Api.Domain;
using static CalendarGates.UnitTests.TestDates;

namespace CalendarGates.UnitTests;

public class Friday13CalculatorTests
{
    [Test]
    [Arguments(2015, new[] { "2015-02-13", "2015-03-13", "2015-11-13" })]
    [Arguments(2025, new[] { "2025-06-13" })]
    [Arguments(2026, new[] { "2026-02-13", "2026-03-13", "2026-11-13" })]
    [Arguments(9999, new[] { "9999-08-13" })]
    public async Task ListsFridaysThe13thInYear(int year, string[] expected)
    {
        var dates = Friday13Calculator.InYear(year);

        await Assert.That(dates).IsEquivalentTo(expected.Select(D));
    }

    [Test]
    public async Task EverySupportedYearHasOneToThree()
    {
        for (var year = Years.Min; year <= Years.Max; year++)
        {
            await Assert.That(Friday13Calculator.InYear(year).Count).IsBetween(1, 3);
        }
    }

    [Test]
    [Arguments(1582)]
    [Arguments(10000)]
    public async Task RejectsUnsupportedYears(int year)
    {
        await Assert
            .That(() => Friday13Calculator.InYear(year))
            .Throws<ArgumentOutOfRangeException>();
    }

    [Test]
    [Arguments("2026-02-12", "2026-02-13")]
    [Arguments("2026-02-13", "2026-02-13")] // on the day counts
    [Arguments("2026-02-14", "2026-03-13")]
    [Arguments("2026-03-14", "2026-11-13")] // longest gap of 2026
    [Arguments("2026-11-14", "2027-08-13")] // across a year boundary
    public async Task FindsNextOnOrAfter(string from, string expected)
    {
        await Assert.That(Friday13Calculator.NextOnOrAfter(D(from))).IsEqualTo(D(expected));
    }

    [Test]
    public async Task ReturnsNullPastTheLastRepresentableOne()
    {
        await Assert.That(Friday13Calculator.NextOnOrAfter(D("9999-08-14"))).IsNull();
    }
}
