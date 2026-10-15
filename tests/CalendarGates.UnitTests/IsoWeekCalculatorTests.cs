using CalendarGates.Api.Domain;
using static CalendarGates.UnitTests.TestDates;

namespace CalendarGates.UnitTests;

public class IsoWeekCalculatorTests
{
    [Test]
    [Arguments("2026-02-12", 2026, 7)]
    [Arguments("2015-12-31", 2015, 53)]
    [Arguments("2020-12-31", 2020, 53)]
    [Arguments("2021-01-03", 2020, 53)] // January date in the previous ISO year
    [Arguments("2024-12-30", 2025, 1)] // December date in the next ISO year
    [Arguments("2026-12-31", 2026, 53)]
    [Arguments("2027-01-01", 2026, 53)]
    [Arguments("2027-01-04", 2027, 1)]
    public async Task ReturnsIsoYearAndWeek(string date, int isoYear, int week)
    {
        var info = IsoWeekCalculator.For(D(date));

        await Assert.That(info.Date).IsEqualTo(D(date));
        await Assert.That(info.IsoYear).IsEqualTo(isoYear);
        await Assert.That(info.Week).IsEqualTo(week);
    }

    [Test]
    [Arguments(2015, 53)]
    [Arguments(2020, 53)]
    [Arguments(2021, 52)]
    [Arguments(2025, 52)]
    [Arguments(2026, 53)]
    [Arguments(2027, 52)]
    public async Task December28IsInTheLastWeek(int year, int weeksInYear)
    {
        var info = IsoWeekCalculator.For(new DateOnly(year, 12, 28));

        await Assert.That(info.Week).IsEqualTo(weeksInYear);
    }

    [Test]
    [Arguments("2026-02-12", "odd")] // week 7
    [Arguments("2026-02-16", "even")] // week 8
    [Arguments("2027-01-01", "odd")] // week 53
    public async Task ParityFollowsWeekNumber(string date, string parity)
    {
        var info = IsoWeekCalculator.For(D(date));

        await Assert.That(info.Parity).IsEqualTo(parity);
    }
}
