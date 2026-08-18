# The Roundtable — Start Here

**What this does:** you talk to Claude, like you already do. Claude quietly asks
GPT and Grok when they'd help, checks their answers, and gives you one reply.
You never have to open three tabs and copy things between them.

**What it costs:** nothing. It uses the ChatGPT and SuperGrok accounts you
already pay for. It cannot spend money — that's locked off in the settings.

**What you have to do:** download a folder, double-click one file, and sign in
twice. About 15 minutes, most of it waiting.

---

## Step 1 — Get the folder onto your PC

1. Go to <https://github.com/KevinxWillette/guitar_builder666>
2. Near the top left there's a button showing a branch name (probably
   **main**). Click it, and pick:
   `claude/killy-ai-roundtable-arch-q0ip34`
3. Click the green **Code** button → **Download ZIP**
4. Find the ZIP in your Downloads. **Right-click it → Extract All → Extract**
5. Open the folder that appears

You should see a file called **INSTALL_ROUNDTABLE_WINDOWS.bat** in there.

## Step 2 — Double-click the installer

Double-click **INSTALL_ROUNDTABLE_WINDOWS.bat**

A black window opens. It will:

- install anything missing (it does this for you — no websites to visit)
- install the GPT helper and the Grok helper
- open a browser twice so you can sign in
- connect everything to Claude

**If Windows shows a blue "Windows protected your PC" box**, that's normal for
a file downloaded from the internet. Click **More info** → **Run anyway**.

**If it says "close this window and double-click again"** — do exactly that.
Windows sometimes needs a fresh start to notice a newly installed program. It
picks up where it left off.

### The one part you do yourself

The installer pauses twice and opens a browser:

- **First:** click **Sign in with ChatGPT**, use your normal ChatGPT login
- **Second:** sign in with the account your SuperGrok subscription is on

Then go back to the black window. That's your whole job.

## Step 3 — Restart Claude properly

This trips everyone up: **closing the Claude window is not enough.**

1. Look at the bottom-right of your screen, near the clock
2. Find the Claude icon (you may need to click the little **^** arrow to see
   hidden icons)
3. **Right-click it → Quit**
4. Open Claude again

## Step 4 — Check it worked

Ask Claude exactly this:

> what does roundtable_status say?

If it comes back naming **GPT** and **Grok**, you're finished.

---

## Using it

Just talk to Claude normally. It decides when to bring the others in.

Things you can say:

- *"get a second opinion on this"*
- *"have Grok tear this apart"*
- *"what did Grok actually say?"* — shows you their raw words
- *"ask GPT and Grok both and tell me where they disagree"*

You'll mostly never notice it happening. That's the point.

---

## If something goes wrong

**The black window closed instantly.** It shouldn't — it's built to stay open.
If it vanished, right-click the .bat → it may be blocked by Windows; unblock it
via right-click → Properties → tick **Unblock** → OK.

**It said a helper failed to install.** Copy the text in the black window (click
and drag over it, then press Enter to copy) and paste it to Claude. Or take a
photo of the screen. Claude can read either and fix it.

**Claude doesn't know what roundtable_status is.** Claude wasn't fully
restarted. Do Step 3 again, making sure you Quit from the icon near the clock.

**Only GPT shows up, not Grok.** That's fine and it still works — Claude just
has one specialist instead of two. Send Claude the black window's text and it
can sort Grok out.

**Anything else.** Paste this into Claude and it will tell you what's wrong:

> run the roundtable doctor and tell me what's broken

---

## One honest warning

Using GPT and Grok this way draws on the same usage allowance as chatting with
them normally. If you lean on the roundtable heavily one afternoon, you may hit
your ChatGPT or Grok limits sooner that day. It costs no money — just some of
the allowance you already have.
