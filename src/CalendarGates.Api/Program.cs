using System.Text.Json.Serialization;
using CalendarGates.Api.Endpoints;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddProblemDetails();
builder.Services.AddValidation();

// JsonSerializerDefaults.Web reads numbers from strings, so the generated schema said every int
// was `[integer, string]` with a digits pattern (F096). That is honest about *reading*, and no
// endpoint here reads a JSON body at all: every input is a route or query string. Strict makes the
// document say what the API actually writes.
builder.Services.ConfigureHttpJsonOptions(options =>
    options.SerializerOptions.NumberHandling = JsonNumberHandling.Strict
);
builder.Services.AddOpenApi(options =>
    options.AddOperationTransformer(OpenApiDateParameters.Transform)
);
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
