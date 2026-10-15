using CalendarGates.Api.Endpoints;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddProblemDetails();
builder.Services.AddValidation();
builder.Services.AddOpenApi();
builder.Services.AddHealthChecks();

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();

app.MapOpenApi();
app.MapHealthChecks("/health");

app.MapGroup("/api")
    .MapWeekEndpoints()
    .MapFriday13Endpoints()
    .MapEasterEndpoints()
    .MapWorkdaysEndpoints()
    .MapLeapEndpoints()
    .MapVersionEndpoints();

app.Run();

/// <summary>Entry point; public so the integration tests can use it with <c>TestWebApplicationFactory</c>.</summary>
public partial class Program;
