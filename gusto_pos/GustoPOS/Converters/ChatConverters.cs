using System;
using System.Globalization;
using Microsoft.Maui;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;

namespace GustoPOS.Converters;

public class ChatBubbleAlignmentConverter : IValueConverter
{
    public object Convert(object? v, Type t, object? p, CultureInfo c)
        => v is true ? LayoutOptions.End : LayoutOptions.Start;

    public object ConvertBack(object? v, Type t, object? p, CultureInfo c)
        => throw new NotImplementedException();
}

public class ChatBubbleColorConverter : IValueConverter
{
    public object Convert(object? v, Type t, object? p, CultureInfo c)
        => v is true ? Color.FromArgb("#D4EDDA") : Color.FromArgb("#EDEDED");

    public object ConvertBack(object? v, Type t, object? p, CultureInfo c)
        => throw new NotImplementedException();
}

public class ChatBubbleTextColorConverter : IValueConverter
{
    public object Convert(object? v, Type t, object? p, CultureInfo c)
        => v is true ? Color.FromArgb("#1B4332") : Color.FromArgb("#212529");

    public object ConvertBack(object? v, Type t, object? p, CultureInfo c)
        => throw new NotImplementedException();
}
