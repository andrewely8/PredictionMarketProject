import pygame
import backtest

pygame.init()
screen = pygame.display.set_mode((800,800))
clock = pygame.time.Clock()
font1 = pygame.font.SysFont('arial', 25)
font2 = pygame.font.SysFont('arial', 20)

WHITE = (255,255,255)
BLACK = (0,0,0)
FILE_PATH_1 = "./collectedData/MLB/KXMLBGAME-26SEP051915NYYSD.jsonl"

loadingTitleSurface = font1.render(f"Loading", False, BLACK)
screen.fill(WHITE)
screen.blit(loadingTitleSurface,(0,0))
pygame.display.flip()

eventTitleSurface = font1.render(f"Event: {FILE_PATH_1}", False, BLACK)
marketTitleSurface = font1.render(f"Markets:", False, BLACK)

pauseButtonRect = pygame.Rect(250,555,25,25)
speedButtonRect = pygame.Rect(350,555,25,25)

game1 = backtest.MlbGame(FILE_PATH_1)
marketsTracked = game1.getMarkets()
currentTick = 0
replaySpeed = 1
paused = -1
replayerSpeeds = [1,2,10,50,100]
replayerSpeedIdx = 0

#timeAtLoad = pygame.time.get_ticks()

while True:

	mouse_pos = pygame.mouse.get_pos()
	for event in pygame.event.get():
		if event.type == pygame.QUIT:
			pygame.quit()
			raise SystemExit
		elif event.type == pygame.MOUSEBUTTONUP:
			print(pygame.mouse.get_pos())

			if pauseButtonRect.collidepoint(mouse_pos):
				paused *= -1

			if speedButtonRect.collidepoint(mouse_pos):
				replayerSpeedIdx += 1
				replayerSpeedIdx = replayerSpeedIdx % len(replayerSpeeds)
				replaySpeed = replayerSpeeds[replayerSpeedIdx]

	timeTickTextSurface = font1.render(f"Tick: {currentTick} ms", False, BLACK)
	game1.checkEvent(currentTick)
	orderBooks = game1.getOrderBooks()

	screen.fill(WHITE)
	screen.blit(eventTitleSurface,(0,0))
	screen.blit(marketTitleSurface,(0,50))

	for i,m in enumerate(marketsTracked):
		gameTextSurface = font2.render(m, False, BLACK)
		screen.blit(gameTextSurface,(0,100+i*75))

		topOfBook = game1.getTopOfBook(m)

		pygame.draw.rect(screen,BLACK,(425,100+i*75,50,50),2)
		bestYesAskTextSurface = font2.render(str(topOfBook['best_yes_ask_dollars']), False, BLACK)
		screen.blit(bestYesAskTextSurface, (425,100+i*75))

		pygame.draw.rect(screen,BLACK,(500,100+i*75,50,50),2)
		bestYesAskTextSurface = font2.render(str(topOfBook['best_no_ask_dollars']), False, BLACK)
		screen.blit(bestYesAskTextSurface, (500,100+i*75))

	screen.blit(timeTickTextSurface,(0,550))


	pauseStatusText = font2.render(f"{paused}", False, BLACK)
	speedStatusText = font2.render(f"{replaySpeed}", False, BLACK)
	pygame.draw.rect(screen,BLACK,pauseButtonRect)
	pygame.draw.rect(screen,BLACK,speedButtonRect)
	screen.blit(pauseStatusText,(255,525))
	screen.blit(speedStatusText,(355,525))

	
	pygame.display.flip()
	dt = clock.tick(60)
	if paused == -1:
		currentTick += dt * replaySpeed
	elif paused == 1:
		print(game1.numUpdates)
	#currentTick = pygame.time.get_ticks()-timeAtLoad
