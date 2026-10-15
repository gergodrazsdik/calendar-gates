namespace CalendarGates.Api.Domain;

/// <summary>Supported year range: the Gregorian calendar (1583, first full year) up to <see cref="DateOnly.MaxValue"/>.</summary>
public static class Years
{
    public const int Min = 1583;
    public const int Max = 9999;

    public static bool IsSupported(int year) => year is >= Min and <= Max;

    internal static void ThrowIfUnsupported(int year)
    {
        if (!IsSupported(year))
        {
            throw new ArgumentOutOfRangeException(
                nameof(year),
                year,
                $"Year must be between {Min} and {Max}."
            );
        }
    }
}
