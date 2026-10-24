import type { ReactNode } from 'react'
import type { User } from '../account'
import { DryRunDemo } from '../components/DryRunDemo'
import { ThemeMenu } from '../components/ThemePicker'
import { linkTo } from '../router'

const REPO = 'https://github.com/devrajrawat9027562124-web/kaaran'

interface NavProps {
  user: User | null
  accountLinks?: boolean  // Log in / Sign up (or Open Kaaran); not on the login page itself
  children?: ReactNode
}

export function SiteNav({ user, accountLinks = true, children }: NavProps) {
  return (
    <header className="site-nav">
      <a className="brand" href={linkTo('home')}>
        Kaaran <span className="brand-deva" lang="hi">कारण</span>
      </a>
      <nav aria-label="Site">
        {children}
        <ThemeMenu />
        {!accountLinks ? null : user ? (
          <a className="button-link primary" href={linkTo('app')}>Open Kaaran</a>
        ) : (
          <>
            <a className="nav-link" href={linkTo('login')}>Log in</a>
            <a className="button-link primary" href={linkTo('signup')}>Sign up</a>
          </>
        )}
      </nav>
    </header>
  )
}

export function Home({ user }: { user: User | null }) {
  return (
    <div className="site home">
      <SiteNav user={user}>
        <a className="nav-link" href="#how">How it works</a>
      </SiteNav>

      <main>
        <section className="hero">
          <div className="hero-copy">
            <h1>Ask your program why.</h1>
            <p className="lead">
              Kaaran runs your Python, C or C++ program one line at a time and fills in the dry-run table as it
              goes. When a value looks wrong, ask why, and it marks the lines that made it.
            </p>
            <div className="hero-actions">
              <a className="button-link primary big" href={linkTo('app')}>Try it now</a>
              {!user && <a className="button-link big" href={linkTo('signup')}>Sign up to save programs</a>}
            </div>
            <p className="hero-note">No account needed to try it. Python runs right in your browser.</p>
          </div>
          <DryRunDemo />
        </section>

        <section id="how" className="how" aria-labelledby="how-heading">
          <h2 id="how-heading">How it works</h2>
          <ol className="how-steps">
            <li>
              <h3>Run</h3>
              <p>Paste your program or pick an example, and press Run. If it reads input, type it in the
                terminal when it asks, as you would on your own computer.</p>
            </li>
            <li>
              <h3>Step through</h3>
              <p>Go forward and back one line at a time. Each change is drawn as it happens: the variables,
                the call stack, the memory and the dry-run table.</p>
            </li>
            <li>
              <h3>Ask why</h3>
              <p>Press Why? next to any value or output line. Kaaran follows the run backwards and marks every
                line that led to it.</p>
            </li>
          </ol>
        </section>

        <section className="more" aria-labelledby="more-heading">
          <h2 id="more-heading">Made for the programs you write in class</h2>
          <dl className="features">
            <div>
              <dt>Menus and input</dt>
              <dd>Programs that use <code>scanf</code>, <code>cin</code> or <code>input()</code> run like they
                would in a terminal. Then Kaaran explains that exact run, with what you typed.</dd>
            </div>
            <div>
              <dt>Linked lists and trees</dt>
              <dd>Objects and <code>malloc</code>'d structs are drawn as boxes and arrows, and a binary search
                tree reads in sorted order.</dd>
            </div>
            <div>
              <dt>Explanations you can check</dt>
              <dd>If it's set up, Claude explains a step in plain words, and every value it mentions is checked
                against your run.</dd>
            </div>
            <div>
              <dt>Your programs, saved</dt>
              <dd>With an account, save the programs you're working on and open them again later, on any
                computer.</dd>
            </div>
          </dl>
        </section>
      </main>

      <footer className="site-footer">
        <p>Kaaran (<span lang="hi">कारण</span>) means cause.</p>
        <a href={REPO}>Source code on GitHub</a>
      </footer>
    </div>
  )
}
