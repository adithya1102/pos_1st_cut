using System;
using System.Globalization;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
namespace GustoPOS.Converters;
public class VegColorConverter : IValueConverter {
    public object Convert(object? v, Type t, object? p, CultureInfo c)
        => v is true ? Color.FromArgb("#28A745") : Color.FromArgb("#DC3545");
    public object ConvertBack(object? v, Type t, object? p, CultureInfo c) => throw new NotImplementedException();
}
public class VegLabelConverter : IValueConverter {
    public object Convert(object? v, Type t, object? p, CultureInfo c)
        => v is true ? "VEG" : "NON-VEG";
    public object ConvertBack(object? v, Type t, object? p, CultureInfo c) => throw new NotImplementedException();
}
public class AvailabilityLabelConverter : IValueConverter {
    public object Convert(object? v, Type t, object? p, CultureInfo c)
        => v is true ? "Available" : "Unavailable";
    public object ConvertBack(object? v, Type t, object? p, CultureInfo c) => throw new NotImplementedException();
}
