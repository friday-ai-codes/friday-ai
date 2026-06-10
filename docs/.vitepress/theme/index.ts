import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme'
import FlowPipeline from './components/FlowPipeline.vue'
import LinkCard from './components/LinkCard.vue'
import LinkCards from './components/LinkCards.vue'
import Steps from './components/Steps.vue'
import './style.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('FlowPipeline', FlowPipeline)
    app.component('LinkCard', LinkCard)
    app.component('LinkCards', LinkCards)
    app.component('Steps', Steps)
  },
} satisfies Theme
