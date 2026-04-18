# Development in Xcode

A practical guide for developers coming from web dev who are new to Xcode and Swift/SwiftUI.

## Running the App

Hit **Cmd+R** (or the play button in the top-left). Xcode builds your Swift code, launches the iOS Simulator on your Mac, and installs your app in it. You'll see a virtual iPhone on screen that you can tap around in.

The first build takes a while since it needs to compile all dependencies (like the Supabase SDK). Subsequent builds are much faster.

## Picking a Simulator Device

The device selector is at the top center of Xcode. You can pick which iPhone model to simulate (iPhone 16 Pro, SE, etc.). You need to have the iOS Simulator runtime downloaded — check **Xcode → Settings → Platforms** to manage installed simulators.

## Hot Reload (Sort Of)

Xcode doesn't have true hot reload like React or Next.js. When you change code and hit **Cmd+R** again, it recompiles and relaunches the app. This is fast for small changes (a few seconds) but you lose your app state each time.

The closest thing to hot reload is **SwiftUI Previews**. In any SwiftUI view file, add a `#Preview` block at the bottom and Xcode renders a live preview in the canvas on the right side of the editor. The canvas updates as you type without recompiling the whole app. This is your best friend for iterating on UI.

Toggle the preview canvas with **Cmd+Option+Enter**.

## The Build Cycle

1. Edit a `.swift` file and save.
2. Press **Cmd+R**.
3. Xcode compiles the project.
4. The app launches in the simulator.

If there are errors, they show inline in the editor with red markers and in the Issue Navigator (**Cmd+5**). Unlike TypeScript where you can run with warnings, Swift won't compile if there are type errors — it's strict.

## Debugging

When the app is running, you can set breakpoints by clicking the line number gutter. The app pauses at that line and you can inspect variables in the debug panel at the bottom of Xcode.

`print()` statements show up in the console at the bottom — that's your `console.log` equivalent.

## File Structure

You edit `.swift` files directly in Xcode's editor. Every SwiftUI view is a struct that conforms to `View` with a `body` property:

```swift
struct HomeView: View {
    var body: some View {
        Text("Hello, Sevino")
    }
}

#Preview {
    HomeView()
}
```

The pattern is similar in spirit to React components.

## Running Tests

Press **Cmd+U** to run the full test suite (the XCTest targets). You can also run individual tests by clicking the diamond icon next to a test function in the editor.

## Key Shortcuts

| Shortcut | Action |
|---|---|
| Cmd+R | Build and run |
| Cmd+U | Run tests |
| Cmd+B | Build without running |
| Cmd+. | Stop the running app |
| Cmd+Option+Enter | Toggle SwiftUI preview canvas |
| Cmd+5 | Open Issue Navigator (errors) |
| Cmd+Shift+K | Clean build folder |

## Mental Model Shift from Web Dev

There's no browser, no dev server, no `localhost:3000`. The simulator is your dev environment. There's no file watcher rebuilding in the background — you explicitly build with **Cmd+R**. It's more like compiled Go or Rust than interpreted JavaScript, but the feedback loop is still tight enough (2–5 seconds for incremental builds).