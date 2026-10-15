using CalendarGates.Api.Domain;
using static CalendarGates.UnitTests.TestDates;

namespace CalendarGates.UnitTests;

public class WorkdaysCalculatorTests
{
    [Test]
    [Arguments("2026-10-12", "2026-10-18", 5)] // Monday to Sunday
    [Arguments("2026-10-12", "2026-10-12", 1)] // same weekday
    [Arguments("2026-10-17", "2026-10-17", 0)] // same Saturday
    [Arguments("2026-10-17", "2026-10-18", 0)] // weekend only
    [Arguments("2026-10-16", "2026-10-19", 2)] // Friday to Monday
    [Arguments("2020-02-28", "2020-03-02", 2)] // across a leap day
    [Arguments("2026-01-01", "2026-12-31", 261)]
    [Arguments("2026-02-12", "2036-02-12", 2609)] // the maximum span
    public async Task CountsMondayToFridayInclusive(string from, string to, int expected)
    {
        await Assert.That(WorkdaysCalculator.Count(D(from), D(to))).IsEqualTo(expected);
    }

    [Test]
    public async Task RejectsReversedRange()
    {
        await Assert
            .That(() => WorkdaysCalculator.Count(D("2026-10-18"), D("2026-10-12")))
            .Throws<ArgumentException>();
    }
}
